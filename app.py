from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from diagnostics import (
    ApplicationStartupError,
    StartupStep,
    build_sanitized_diagnostics,
    configure_local_logger,
    log_sanitized_exception,
    run_startup_steps,
    startup_failure_diagnostics,
)
from csv_export_safety import (
    dataframe_to_spreadsheet_safe_csv,
    write_dataframe_spreadsheet_safe_csv,
)
from database import (
    DB_PATH, SCHEMA_VERSION, DatabaseMaintenanceError, add_watchlist_row, apply_history_retention,
    create_database_backup, dashboard_metrics, delete_saved_search, delete_watchlist_item, init_db,
    inspect_database_backup,
    latest_batch_summary, latest_opportunities, latest_batch_metrics, latest_batch_opportunities,
    preview_history_retention, recent_activity, list_saved_searches, list_search_runs, list_watchlist,
    log_search_run, restore_database_backup, save_opportunity_batch,
    save_opportunity_batch_outcome, save_search,
)
from ebay_client import (
    EbayApiError,
    EbayCredentials,
    normalize_ebay_items,
    search_ebay,
    validate_environment,
)
from input_validation import (
    InputValidationError,
    MAX_CSV_UPLOAD_MB,
    load_listing_csv,
    load_settings_file,
    load_valuation_csv,
    validate_search_inputs,
    validate_valuation_frame,
)
from local_file_persistence import (
    save_settings_atomically,
    save_valuation_frame_atomically,
)
from local_runtime_security import secure_optional_private_file
from profit_engine import analyze_listings
from search_relevance import filter_search_results
from scout_engine import run_scout_engine
from search_workflows import (
    RunOutcome,
    build_run_outcome,
    clear_result_state,
    combine_board_results,
    empty_analysis_frame,
    stable_analysis_frame,
)
from valuation_renewal import (
    build_valuation_renewal_report,
    summarize_valuation_renewal,
)

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "config" / "settings.json"
SAMPLE_LISTINGS_PATH = ROOT / "sample_data" / "sample_listings.csv"
CARD_VALUES_PATH = ROOT / "sample_data" / "card_values.csv"
OUTPUT_DIR = ROOT / "output"
DATABASE_BACKUP_DIR = OUTPUT_DIR / "database_backups"
DIAGNOSTIC_LOG_DIR = OUTPUT_DIR / "logs"
VERSION_PATH = ROOT / "VERSION"
ENV_PATH = ROOT / ".env"


def read_application_version() -> str:
    try:
        version = VERSION_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "Unknown"
    return version or "Unknown"


APPLICATION_VERSION = read_application_version()

st.set_page_config(
    page_title=f"CardProfitHunter {APPLICATION_VERSION}",
    page_icon="📈",
    layout="wide",
)
logger_setup = configure_local_logger(DIAGNOSTIC_LOG_DIR)
diagnostic_logger = logger_setup.logger


def load_settings() -> dict:
    return load_settings_file(SETTINGS_PATH)


def load_local_environment() -> bool:
    secure_optional_private_file(ENV_PATH)
    return load_dotenv(ENV_PATH)


def save_settings(settings: dict) -> None:
    save_settings_atomically(SETTINGS_PATH, settings)


def save_output(df: pd.DataFrame, filename: str) -> Path:
    path = OUTPUT_DIR / filename
    return write_dataframe_spreadsheet_safe_csv(df, path)


def valuation_data_warning(values: pd.DataFrame) -> None:
    renewal_report = build_valuation_renewal_report(values)
    freshness = renewal_report["freshness_status"]
    renewal_summary = summarize_valuation_renewal(renewal_report)
    if freshness.eq("Non-actionable").any():
        st.warning(
            "Demonstration and unverified card values are blocked from generating "
            "BUY or OFFER recommendations."
        )
    if renewal_summary["due_soon"]:
        due_soon_count = renewal_summary["due_soon"]
        valuation_noun = "valuation" if due_soon_count == 1 else "valuations"
        st.warning(
            f"{due_soon_count} verified card {valuation_noun} expire within 30 days. "
            "Review current exact-card sold comparables before their expiry dates."
        )
    blocked_freshness = freshness.isin(
        {"Expired", "Missing provenance", "Invalid provenance"}
    )
    if blocked_freshness.any():
        st.error(
            "One or more card valuations are expired or lack valid provenance. "
            "They remain non-actionable until reviewed in the Card Values tab."
        )

def metrics_block(df: pd.DataFrame) -> None:
    if df.empty:
        st.warning("No results to display.")
        return
    counts = df["recommended_action"].value_counts()
    scout_count = 0
    if "scout_candidate" in df.columns:
        scout_count = int(df["scout_candidate"].fillna(False).astype(bool).sum())
    pass_count = int(counts.get("PASS", 0))
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Verified Buys", int(counts.get("BUY_RAW_FLIP", 0) + counts.get("BUY_GRADE_PSA", 0)))
    c2.metric("Verified Offers", int(counts.get("OFFER", 0)))
    c3.metric("Scout Candidates", scout_count)
    c4.metric("Watch", int(counts.get("WATCH", 0)))
    c5.metric("Financial Pass", pass_count)
    c6.metric("Listings", len(df))


def result_table(df: pd.DataFrame) -> None:
    preferred = ["scout_recommendation", "financially_verified", "requires_comp_verification",
                 "recommendation_basis", "scout_score", "recommended_action", "total_score",
                 "grading_candidate", "grading_signal_score", "listing_listing_class",
                 "parsed_year", "parsed_manufacturer", "parsed_product", "parsed_parallel",
                 "parsed_card_number", "parsed_serial_number", "best_path", "best_expected_profit",
                 "best_expected_roi_pct", "suggested_offer", "total_price", "title",
                 "matched_card", "seller_username", "condition", "item_url", "flags"]
    display_df = df.loc[:, ~df.columns.duplicated(keep="last")].copy()
    cols = (
        [column for column in preferred if column in display_df.columns]
        + [
            column
            for column in display_df.columns
            if column not in preferred
        ]
    )
    st.dataframe(
        display_df.loc[:, cols],
        width="stretch",
        hide_index=True,
    )


def select_actionable_results(
    frame: pd.DataFrame,
    recommendation_limit: int,
    include_offers: bool = False,
) -> pd.DataFrame:
    """Return the strongest purchase recommendations from an analyzed candidate pool."""
    if frame is None or frame.empty or "recommended_action" not in frame.columns:
        return stable_analysis_frame(pd.DataFrame())

    allowed_actions = {"BUY_GRADE_PSA", "BUY_RAW_FLIP"}
    if include_offers:
        allowed_actions.add("OFFER")

    actionable = frame[frame["recommended_action"].isin(allowed_actions)].copy()
    if actionable.empty:
        return stable_analysis_frame(actionable)

    action_priority = {
        "BUY_GRADE_PSA": 3,
        "BUY_RAW_FLIP": 2,
        "OFFER": 1,
    }
    actionable["_action_priority"] = (
        actionable["recommended_action"].map(action_priority).fillna(0)
    )

    sort_columns = ["_action_priority"]
    for column in ("total_score", "best_expected_profit", "best_expected_roi_pct"):
        if column in actionable.columns:
            actionable[column] = pd.to_numeric(actionable[column], errors="coerce")
            sort_columns.append(column)

    actionable = actionable.sort_values(
        sort_columns,
        ascending=[False] * len(sort_columns),
        na_position="last",
    ).head(max(int(recommendation_limit), 1))

    return stable_analysis_frame(
        actionable.drop(columns=["_action_priority"], errors="ignore")
    ).reset_index(drop=True)


def show_run_outcome(label: str, outcome: RunOutcome) -> None:
    display_label = "Search" if label == "Recommended Buy Search" else label

    if outcome.status == "success":
        result_noun = "result" if outcome.result_count == 1 else "results"
        st.success(
            f"{display_label} completed with "
            f"{outcome.result_count} {result_noun}."
        )
    elif outcome.status == "empty":
        st.info(
            f"{display_label} completed successfully but returned no listings."
        )
    elif outcome.status == "partial":
        st.warning(
            f"{display_label} partially completed: "
            f"{outcome.successful_count} succeeded, "
            f"{outcome.failed_count} failed, and "
            f"{outcome.result_count} results are current."
        )
    else:
        st.error(f"{display_label} failed: all attempted searches failed.")

    st.caption(f"Completed: {outcome.completed_at}")
    if outcome.errors:
        st.warning("Search failures:\n- " + "\n- ".join(outcome.errors))


st.title(f"CardProfitHunter {APPLICATION_VERSION}")
st.caption("Executive Dashboard • Daily Buy Board • Live eBay sourcing • Opportunity history")
if logger_setup.warning:
    st.warning(logger_setup.warning)
try:
    startup_values = run_startup_steps((
        StartupStep(
            "environment",
            "STARTUP_ENVIRONMENT",
            "Local environment configuration could not be loaded.",
            load_local_environment,
        ),
        StartupStep(
            "database",
            "STARTUP_DATABASE",
            "The local database could not be initialized.",
            init_db,
        ),
        StartupStep(
            "settings",
            "STARTUP_SETTINGS",
            "Application settings could not be loaded. Check the local settings file.",
            load_settings,
        ),
        StartupStep(
            "card_values",
            "STARTUP_VALUATIONS",
            "Card valuation data could not be loaded. Check the local valuation file.",
            lambda: load_valuation_csv(CARD_VALUES_PATH),
        ),
        StartupStep(
            "diagnostics",
            "STARTUP_DIAGNOSTICS",
            "Sanitized application diagnostics could not be generated.",
            lambda: build_sanitized_diagnostics(
                environ=os.environ,
                version_path=VERSION_PATH,
                database_path=DB_PATH,
                settings_path=SETTINGS_PATH,
                valuation_path=CARD_VALUES_PATH,
                output_path=OUTPUT_DIR,
                supported_schema_version=SCHEMA_VERSION,
                local_logging_enabled=logger_setup.enabled,
            ),
        ),
    ), on_error=lambda code, error, context: log_sanitized_exception(
        diagnostic_logger,
        code,
        error,
        context,
    ))
except ApplicationStartupError as exc:
    st.error(str(exc))
    st.caption("Startup stopped safely. The diagnostic report excludes secrets and exception details.")
    st.json(startup_failure_diagnostics(exc))
    st.stop()
settings = startup_values["settings"]
card_values = startup_values["card_values"]
startup_diagnostics = startup_values["diagnostics"]
valuation_data_warning(card_values)

with st.sidebar:
    st.header("eBay Connection")
    configured_environment = os.getenv("EBAY_ENVIRONMENT")
    environment_error = None
    if configured_environment is None or not configured_environment.strip():
        env_default = "sandbox"
    else:
        try:
            env_default = validate_environment(configured_environment)
        except EbayApiError as exc:
            env_default = None
            environment_error = str(exc)
    environment_options = ["sandbox", "production"]
    environment = st.selectbox(
        "Environment",
        environment_options,
        index=environment_options.index(env_default) if env_default else None,
        placeholder="Explicitly choose an eBay environment",
    )
    if environment_error:
        st.error(environment_error)
    marketplace = st.text_input("Marketplace ID", value=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US"))
    client_id = st.text_input("Client ID", value=os.getenv("EBAY_CLIENT_ID", ""))
    client_secret = st.text_input("Client Secret", value=os.getenv("EBAY_CLIENT_SECRET", ""), type="password")
    if client_id and client_secret:
        st.success("Credentials loaded locally.")
    else:
        st.info("Add credentials in .env or enter them here.")

    st.divider(); st.header("Profit Settings")
    fields = [
        ("ebay_fee_pct", "eBay fee %", 0.0, 0.30, 0.0025, "%.4f"),
        ("purchase_tax_pct", "Purchase tax %", 0.0, 0.30, 0.0025, "%.4f"),
        ("promoted_listing_fee_pct", "Promoted listing fee %", 0.0, 0.50, 0.0025, "%.4f"),
        ("return_defect_allowance_pct", "Return/defect allowance %", 0.0, 0.50, 0.0025, "%.4f"),
        ("grading_loss_risk_pct", "Grading loss risk %", 0.0, 0.25, 0.0025, "%.4f"),
        ("raw_flip_shipping_allowance", "Raw flip shipping/supplies", 0.0, None, 1.0, None),
        ("psa_grading_fee", "PSA grading fee", 0.0, None, 1.0, None),
        ("psa_shipping_insurance_allowance", "PSA shipping/insurance", 0.0, None, 1.0, None),
        ("psa_selling_shipping_allowance", "PSA sale shipping", 0.0, None, 1.0, None),
        ("minimum_raw_flip_profit", "Minimum raw profit", 0.0, None, 5.0, None),
        ("minimum_raw_flip_roi_pct", "Minimum raw ROI %", 0.0, None, 5.0, None),
        ("minimum_psa_expected_profit", "Minimum PSA profit", 0.0, None, 5.0, None),
        ("minimum_psa_expected_roi_pct", "Minimum PSA ROI %", 0.0, None, 5.0, None),
    ]
    st.caption(
        "Rates are decimal expected-cost assumptions: 0.10 means 10%. "
        "Use your actual tax and selling history when available."
    )
    for key, label, minv, maxv, step, fmt in fields:
        kwargs = dict(min_value=minv, value=float(settings.get(key, 0)), step=step)
        if maxv is not None: kwargs["max_value"] = maxv
        if fmt: kwargs["format"] = fmt
        settings[key] = st.number_input(label, **kwargs)
    settings["raw_only"] = st.checkbox("Raw only", value=bool(settings.get("raw_only", True)))
    if st.button("Save Settings"):
        try:
            save_settings(settings)
        except InputValidationError as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "SETTINGS_VALIDATION_FAILED",
                exc,
                "settings.save.validate",
            )
            st.error(str(exc))
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "SETTINGS_SAVE_FAILED",
                exc,
                "settings.save.persist",
            )
            st.error("Settings could not be saved. See local diagnostics.")
        else:
            st.success("Settings saved.")

dashboard_tab, daily_tab, live_tab, saved_tab, watch_tab, sample_tab, values_tab, setup_tab = st.tabs([
    "Dashboard", "Daily Buy Board", "Live Search", "Saved Searches", "Watchlist", "Sample Analysis", "Card Values", "Setup"
])

with dashboard_tab:
    st.subheader("Executive Dashboard")
    kpis = latest_batch_metrics()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Listings Analyzed", f"{kpis['listings_analyzed']:,}")
    c2.metric("Buy Candidates", f"{kpis['buy_candidates']:,}")
    c3.metric("Potential Profit", f"${kpis['potential_profit']:,.2f}")
    c4.metric("Average ROI", f"{kpis['average_roi_pct']:.1f}%")
    c5.metric("Highest Score", f"{kpis['highest_score']:.1f}")

    if kpis["status"] == "failed":
        st.error(
            "The latest Daily Buy Board run failed. Prior opportunities are not "
            "shown as current."
        )
    elif kpis["status"] == "empty":
        st.info("The latest Daily Buy Board run completed with no listings.")
    elif kpis["status"] == "partial":
        st.warning(
            "The latest Daily Buy Board run was partial: "
            f"{kpis['successful_count']} searches succeeded and "
            f"{kpis['failed_count']} failed."
        )

    best = kpis.get("best_opportunity")
    if best:
        st.markdown("### Best Current Opportunity")
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"**{best['title']}**")
            st.caption(f"Last Daily Buy Board refresh: {kpis['created_at']}")
            if best.get("item_url"):
                st.link_button("Open on eBay", best["item_url"])
        with right:
            st.metric("Expected Profit", f"${float(best['expected_profit'] or 0):,.2f}")
            st.metric("Expected ROI", f"{float(best['expected_roi_pct'] or 0):.1f}%")
    else:
        if kpis["batch_id"]:
            st.info("The latest Daily Buy Board run found no actionable financial opportunities.")
        else:
            st.info("Run the Daily Buy Board to populate executive metrics and ranked opportunities.")

    st.markdown("### Top Opportunities from Latest Run")
    current = latest_batch_opportunities(25)
    if current.empty:
        if kpis["batch_id"]:
            st.info("No actionable opportunities were found in the latest run.")
        else:
            st.info("No opportunity snapshot is available yet.")
    else:
        st.dataframe(current, width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.markdown("### Saved Search Performance")
        summary = latest_batch_summary()
        if summary.empty:
            st.caption("No saved-search performance data yet.")
        else:
            st.dataframe(summary, width="stretch", hide_index=True)
    with right:
        st.markdown("### Recent Activity")
        activity = recent_activity(12)
        if activity.empty:
            st.caption("No recent searches or watchlist activity.")
        else:
            st.dataframe(activity, width="stretch", hide_index=True)

    m = dashboard_metrics()
    st.markdown("### Business System Snapshot")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Saved Searches", m["saved_searches"])
    s2.metric("Watchlist", m["watchlist"])
    s3.metric("All Search Runs", m["search_runs"])
    s4.metric("Stored Opportunities", m["opportunities"])

with daily_tab:
    st.subheader("Daily Buy Board")
    st.write("Runs every saved search, scores live listings, combines the results, and stores a historical snapshot.")
    saved_daily = list_saved_searches()
    if saved_daily.empty:
        st.warning("Create at least one saved search first.")
    else:
        st.dataframe(saved_daily[["name", "query", "limit_count", "sort_order", "max_price"]], width="stretch", hide_index=True)
        max_per_search = st.number_input("Maximum results per saved search", 1, 200, 50, 10)
        minimum_score = st.number_input("Minimum score to show", 0.0, 1000.0, 0.0, 5.0)
        if st.button("Run Daily Buy Board", type="primary"):
            clear_result_state(
                st.session_state,
                "daily_board",
                "daily_board_outcome",
            )
            combined = []
            errors = []
            successful_count = 0
            empty_count = 0
            attempted_count = len(saved_daily)
            batch_id = uuid.uuid4().hex
            run_warnings = []

            if environment is None:
                errors.append(
                    "Invalid eBay environment configuration; explicitly choose an environment."
                )
                board = empty_analysis_frame(("saved_search", "search_query"))
            else:
                credentials = EbayCredentials(
                    client_id.strip(),
                    client_secret.strip(),
                    environment,
                    marketplace.strip() or "EBAY_US",
                )
                progress = st.progress(0, text="Starting saved searches...")
                for pos, row in saved_daily.reset_index(drop=True).iterrows():
                    search_name = str(row["name"])
                    try:
                        progress.progress(
                            pos / len(saved_daily),
                            text=f"Searching: {search_name}",
                        )
                        validated_query, validated_category_ids = validate_search_inputs(
                            row["query"],
                            row["category_ids"],
                        )
                        items = search_ebay(
                            credentials,
                            validated_query,
                            min(int(row["limit_count"]), int(max_per_search)),
                            str(row["sort_order"]),
                            validated_category_ids,
                            float(row["max_price"])
                            if pd.notna(row["max_price"])
                            and float(row["max_price"]) > 0
                            else None,
                        )
                        items = filter_search_results(items, validated_query)
                        listings = normalize_ebay_items(items)
                        scored = stable_analysis_frame(
                            analyze_listings(
                                listings,
                                card_values,
                                settings,
                            )
                        )
                        scored["saved_search"] = search_name
                        scored["search_query"] = validated_query
                        if not scored.empty:
                            save_opportunity_batch(
                                batch_id,
                                int(row["id"]),
                                search_name,
                                validated_query,
                                scored,
                            )
                        log_search_run(
                            validated_query,
                            len(scored),
                            int(row["id"]),
                        )
                        successful_count += 1
                        if scored.empty:
                            empty_count += 1
                        else:
                            combined.append(scored)
                    except EbayApiError as exc:
                        log_sanitized_exception(
                            diagnostic_logger,
                            "DAILY_SEARCH_API_FAILED",
                            exc,
                            "daily_board.search.api",
                        )
                        errors.append(f"{search_name}: {exc}")
                    except InputValidationError as exc:
                        log_sanitized_exception(
                            diagnostic_logger,
                            "DAILY_SEARCH_VALIDATION_FAILED",
                            exc,
                            "daily_board.search.validate",
                        )
                        errors.append(f"{search_name}: {exc}")
                    except Exception as exc:
                        log_sanitized_exception(
                            diagnostic_logger,
                            "DAILY_SEARCH_PROCESSING_FAILED",
                            exc,
                            "daily_board.search.process",
                        )
                        errors.append(f"{search_name}: Search processing failed.")
                progress.progress(1.0, text="Daily Buy Board finished")
                board = combine_board_results(combined, minimum_score)

            outcome = build_run_outcome(
                attempted_count=attempted_count,
                successful_count=successful_count,
                empty_count=empty_count,
                failed_count=(attempted_count if environment is None else len(errors)),
                result_count=len(board),
                errors=errors,
            )
            st.session_state["daily_board"] = board
            st.session_state["daily_board_outcome"] = outcome
            try:
                save_opportunity_batch_outcome(
                    batch_id,
                    status=outcome.status,
                    attempted_count=outcome.attempted_count,
                    successful_count=outcome.successful_count,
                    empty_count=outcome.empty_count,
                    failed_count=outcome.failed_count,
                    result_count=outcome.result_count,
                    completed_at=outcome.completed_at,
                )
            except Exception as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "DAILY_BATCH_OUTCOME_SAVE_FAILED",
                    exc,
                    "daily_board.outcome.persist",
                )
                run_warnings.append(
                    "Daily Buy Board results are available, but the dashboard run "
                    "status could not be saved. See local diagnostics."
                )
            if not board.empty:
                try:
                    save_output(board, "daily_buy_board.csv")
                except Exception as exc:
                    log_sanitized_exception(
                        diagnostic_logger,
                        "DAILY_OUTPUT_SAVE_FAILED",
                        exc,
                        "daily_board.output.save",
                    )
                    run_warnings.append(
                        "Daily Buy Board results are available, but the local output file "
                        "could not be saved. See local diagnostics."
                    )
            st.session_state["daily_board_warnings"] = tuple(run_warnings)
            st.rerun()

        outcome = st.session_state.get("daily_board_outcome")
        if isinstance(outcome, RunOutcome):
            show_run_outcome("Daily Buy Board", outcome)
        for warning in st.session_state.pop("daily_board_warnings", ()):
            st.warning(warning)
        board = st.session_state.get("daily_board")
        if isinstance(board, pd.DataFrame) and not board.empty:
            metrics_block(board)
            result_table(board)
            try:
                st.download_button(
                    "Download Daily Buy Board CSV",
                    dataframe_to_spreadsheet_safe_csv(board).encode("utf-8"),
                    "daily_buy_board.csv",
                    "text/csv",
                )
            except Exception as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "DAILY_DOWNLOAD_PREPARE_FAILED",
                    exc,
                    "daily_board.download.prepare",
                )
                st.error("Daily Buy Board CSV could not be prepared. See local diagnostics.")


with live_tab:
    saved = list_saved_searches()
    options = ["New search"] + saved["name"].tolist() if not saved.empty else ["New search"]
    selected = st.selectbox("Load saved search", options)
    preset = None if selected == "New search" else saved[saved["name"] == selected].iloc[0]
    q = st.text_input(
        "Player or card search",
        value=str(preset["query"]) if preset is not None else "Shohei Ohtani",
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    recommendation_limit = c1.number_input(
        "Recommendations to return",
        1,
        100,
        25,
        5,
    )
    candidate_pool = c2.number_input(
        "Listings to analyze",
        25,
        200,
        int(preset["limit_count"]) if preset is not None else 200,
        25,
    )
    sorts = ["newlyListed", "endingSoonest", "price", "-price"]
    sort = c3.selectbox(
        "eBay sort",
        sorts,
        index=(
            sorts.index(str(preset["sort_order"]))
            if preset is not None and str(preset["sort_order"]) in sorts
            else 0
        ),
    )
    max_price = c4.number_input(
        "Max price",
        0.0,
        value=float(preset["max_price"] or 1000) if preset is not None else 1000.0,
        step=50.0,
    )
    category_ids = c5.text_input(
        "Category IDs",
        value=str(preset["category_ids"] or "") if preset is not None else "",
    )
    include_offers = st.checkbox(
        "Include strong OFFER candidates",
        value=True,
        help="Includes listings where the current asking price is too high but a verified suggested offer may create an acceptable opportunity.",
    )
    include_scout_candidates = st.checkbox(
        "Include unverified Scout candidates",
        value=True,
        help=(
            "Shows promising raw cards that do not yet have an exact verified valuation. "
            "These are discovery candidates—not confirmed BUY recommendations."
        ),
    )
    minimum_scout_score = st.slider(
        "Minimum Scout candidate score",
        min_value=25,
        max_value=90,
        value=40,
        step=5,
        disabled=not include_scout_candidates,
    )
    st.caption(
        "Verified BUY and OFFER recommendations require an exact valuation match. "
        "Unverified Scout candidates are ranked using listing type, grading signals, "
        "rarity, card traits, and seller data, and must be researched before purchase."
    )

    search_name = st.text_input(
        "Saved search name",
        value=selected if selected != "New search" else "",
    )
    if st.button("Save / Update Search"):
        if not search_name.strip():
            st.error("Enter a saved search name.")
        else:
            try:
                validated_query, validated_category_ids = validate_search_inputs(
                    q,
                    category_ids,
                )
            except InputValidationError as exc:
                st.error(str(exc))
            else:
                save_search(
                    search_name,
                    validated_query,
                    int(candidate_pool),
                    sort,
                    max_price if max_price > 0 else None,
                    validated_category_ids,
                )
                st.success("Saved search stored in SQLite.")

    if st.button("Run Live Search & Score", type="primary"):
        clear_result_state(
            st.session_state,
            "last_results",
            "live_search_outcome",
        )
        st.session_state.pop("live_search_diagnostics", None)
        errors = []
        successful_count = 0
        empty_count = 0
        results = empty_analysis_frame()

        try:
            validated_query, validated_category_ids = validate_search_inputs(
                q,
                category_ids,
            )
        except InputValidationError as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "LIVE_SEARCH_VALIDATION_FAILED",
                exc,
                "live_search.validate",
            )
            errors.append(str(exc))

        if errors:
            pass
        elif environment is None:
            errors.append(
                "Invalid eBay environment configuration; explicitly choose an environment."
            )
        else:
            credentials = EbayCredentials(
                client_id.strip(),
                client_secret.strip(),
                environment,
                marketplace.strip() or "EBAY_US",
            )
            try:
                with st.spinner("Searching eBay, evaluating cards, and ranking purchase opportunities..."):
                    items = search_ebay(
                        credentials,
                        validated_query,
                        int(candidate_pool),
                        sort,
                        validated_category_ids,
                        max_price if max_price > 0 else None,
                    )
                    raw_item_count = len(items)
                    items = filter_search_results(items, validated_query)
                    relevant_item_count = len(items)
                    listings = normalize_ebay_items(items)
                    normalized_listing_count = len(listings)
                    results = stable_analysis_frame(
                        run_scout_engine(
                            listings,
                            card_values,
                            settings,
                            validated_query,
                            int(recommendation_limit),
                            include_offers=include_offers,
                            include_scout_candidates=include_scout_candidates,
                            minimum_scout_score=int(minimum_scout_score),
                        )
                    )
                    verified_count = 0
                    scout_count = 0
                    if not results.empty:
                        if "financially_verified" in results.columns:
                            verified_count = int(
                                results["financially_verified"].fillna(False).astype(bool).sum()
                            )
                        if "scout_candidate" in results.columns:
                            scout_count = int(
                                results["scout_candidate"].fillna(False).astype(bool).sum()
                            )
                    st.session_state["live_search_diagnostics"] = {
                        "raw_ebay_results": raw_item_count,
                        "relevant_results": relevant_item_count,
                        "normalized_listings": normalized_listing_count,
                        "verified_recommendations": verified_count,
                        "scout_candidates": scout_count,
                    }
                    successful_count = 1
                    empty_count = int(results.empty)
                    saved_id = None
                    if selected != "New search" and preset is not None:
                        saved_id = int(preset["id"])
                    log_search_run(validated_query, len(results), saved_id)
                    if not results.empty:
                        try:
                            save_output(results, "live_ebay_buy_board.csv")
                        except Exception as exc:
                            log_sanitized_exception(
                                diagnostic_logger,
                                "LIVE_OUTPUT_SAVE_FAILED",
                                exc,
                                "live_search.output.save",
                            )
                            st.warning(
                                "Live Search results are available, but the local output file "
                                "could not be saved. See local diagnostics."
                            )
            except EbayApiError as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "LIVE_SEARCH_API_FAILED",
                    exc,
                    "live_search.api",
                )
                errors.append(str(exc))
                results = empty_analysis_frame()
            except Exception as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "LIVE_SEARCH_PROCESSING_FAILED",
                    exc,
                    "live_search.process",
                )
                errors.append("Live search processing failed.")
                results = empty_analysis_frame()

        outcome = build_run_outcome(
            attempted_count=1,
            successful_count=successful_count,
            empty_count=empty_count,
            failed_count=len(errors),
            result_count=len(results),
            errors=errors,
        )
        st.session_state["last_results"] = results
        st.session_state["live_search_outcome"] = outcome

    outcome = st.session_state.get("live_search_outcome")
    if isinstance(outcome, RunOutcome):
        show_run_outcome("Recommended Buy Search", outcome)
    diagnostics = st.session_state.get("live_search_diagnostics")
    if isinstance(diagnostics, dict):
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Raw eBay", diagnostics.get("raw_ebay_results", 0))
        d2.metric("Relevant", diagnostics.get("relevant_results", 0))
        d3.metric("Normalized", diagnostics.get("normalized_listings", 0))
        d4.metric("Verified", diagnostics.get("verified_recommendations", 0))
        d5.metric("Scout", diagnostics.get("scout_candidates", 0))
    results = st.session_state.get("last_results")
    if isinstance(results, pd.DataFrame) and not results.empty:
        metrics_block(results)

        grading = results[results["recommended_action"] == "BUY_GRADE_PSA"]
        raw_buys = results[results["recommended_action"] == "BUY_RAW_FLIP"]
        offers = results[results["recommended_action"] == "OFFER"]
        if "scout_candidate" in results.columns:
            scout_candidates = results[
                results["scout_candidate"].fillna(False).astype(bool)
            ]
        else:
            scout_candidates = results.iloc[0:0]

        if not grading.empty:
            st.markdown("### Verified Buy-to-Grade Recommendations")
            st.caption(
                "These recommendations have an exact actionable valuation match and pass "
                "the configured financial thresholds. Photo inspection is still required."
            )
            result_table(grading)

        if not raw_buys.empty:
            st.markdown("### Verified Raw Resale Buys")
            result_table(raw_buys)

        if not offers.empty:
            st.markdown("### Verified Offer Candidates")
            result_table(offers)

        if not scout_candidates.empty:
            st.markdown("### Unverified Scout Candidates")
            st.warning(
                "These are discovery candidates, not confirmed BUY recommendations. "
                "They lack an exact verified valuation. Check recent sold comparables, "
                "inspect front and back photos, confirm the exact card/parallel, and review "
                "the seller's return policy before purchasing."
            )
            result_table(scout_candidates)

        try:
            st.download_button(
                "Download Search Results CSV",
                dataframe_to_spreadsheet_safe_csv(results).encode("utf-8"),
                "live_ebay_search_results.csv",
                "text/csv",
            )
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "LIVE_DOWNLOAD_PREPARE_FAILED",
                exc,
                "live_search.download.prepare",
            )
            st.error("Recommended Buys CSV could not be prepared. See local diagnostics.")

        labels = [
            f"{i}: {row.get('title', '')[:90]}"
            for i, row in results.reset_index(drop=True).iterrows()
        ]
        pick = st.selectbox("Add listing to watchlist", labels)
        notes = st.text_input("Watchlist notes")
        if st.button("Add Selected Listing"):
            idx = int(pick.split(":", 1)[0])
            add_watchlist_row(
                results.reset_index(drop=True).iloc[idx].to_dict(),
                notes,
            )
            st.success("Added to watchlist.")

with saved_tab:
    st.subheader("Saved Searches")
    df = list_saved_searches(); st.dataframe(df, width="stretch", hide_index=True)
    if not df.empty:
        delete_id = st.selectbox("Delete saved search", df["id"].tolist(), format_func=lambda x: df.loc[df.id == x, "name"].iloc[0])
        delete_confirmed = st.checkbox(
            "Confirm deletion of the selected saved search",
            key=f"confirm_saved_search_delete_{int(delete_id)}",
        )
        if st.button("Delete Search", disabled=not delete_confirmed):
            delete_saved_search(int(delete_id))
            st.rerun()
    st.subheader("Recent Search Runs"); st.dataframe(list_search_runs(), width="stretch", hide_index=True)

with watch_tab:
    st.subheader("Watchlist")
    watch = list_watchlist(); st.dataframe(watch, width="stretch", hide_index=True)
    if not watch.empty:
        delete_id = st.selectbox("Remove watchlist item", watch["id"].tolist(), format_func=lambda x: watch.loc[watch.id == x, "title"].iloc[0][:100])
        removal_confirmed = st.checkbox(
            "Confirm removal of the selected watchlist item",
            key=f"confirm_watchlist_remove_{int(delete_id)}",
        )
        if st.button("Remove Item", disabled=not removal_confirmed):
            delete_watchlist_item(int(delete_id))
            st.rerun()
        try:
            st.download_button(
                "Download Watchlist CSV",
                dataframe_to_spreadsheet_safe_csv(watch).encode("utf-8"),
                "watchlist.csv",
                "text/csv",
            )
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "WATCHLIST_DOWNLOAD_PREPARE_FAILED",
                exc,
                "watchlist.download.prepare",
            )
            st.error("Watchlist CSV could not be prepared. See local diagnostics.")

with sample_tab:
    st.subheader("Sample Profit Analysis")
    listings_file = st.file_uploader(
        "Listings CSV",
        type=["csv"],
        max_upload_size=MAX_CSV_UPLOAD_MB,
    )
    values_file = st.file_uploader(
        "Card values CSV",
        type=["csv"],
        max_upload_size=MAX_CSV_UPLOAD_MB,
    )
    sample_validation_error = None
    try:
        listings_source = listings_file if listings_file is not None else SAMPLE_LISTINGS_PATH
        values_source = values_file if values_file is not None else CARD_VALUES_PATH
        listings = load_listing_csv(listings_source)
        values = load_valuation_csv(values_source)
    except InputValidationError as exc:
        listings = None
        values = None
        sample_validation_error = str(exc)
        log_sanitized_exception(
            diagnostic_logger,
            "SAMPLE_CSV_VALIDATION_FAILED",
            exc,
            "sample.csv.load",
        )
        st.error(sample_validation_error)
    except Exception as exc:
        listings = None
        values = None
        sample_validation_error = "Sample CSV data could not be loaded."
        log_sanitized_exception(
            diagnostic_logger,
            "SAMPLE_CSV_LOAD_FAILED",
            exc,
            "sample.csv.load",
        )
        st.error("Sample CSV data could not be loaded. See local diagnostics.")
    if st.button("Run Sample Analysis", type="primary"):
        if sample_validation_error:
            st.error("Sample analysis is blocked until the CSV validation errors are corrected.")
        else:
            try:
                result = analyze_listings(listings, values, settings)
            except Exception as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "SAMPLE_ANALYSIS_FAILED",
                    exc,
                    "sample.analysis.run",
                )
                st.error("Sample analysis could not be completed. See local diagnostics.")
            else:
                try:
                    save_output(result, "sample_buy_board.csv")
                except Exception as exc:
                    log_sanitized_exception(
                        diagnostic_logger,
                        "SAMPLE_OUTPUT_SAVE_FAILED",
                        exc,
                        "sample.output.save",
                    )
                    st.warning(
                        "Sample results are available, but the local output file could not "
                        "be saved. See local diagnostics."
                    )
                metrics_block(result)
                result_table(result)

with values_tab:
    st.subheader("Card Values")
    st.caption(
        "Use exact card identifiers and current verified sold comps. Expired, "
        "unverified, and demonstration rows are non-actionable by design."
    )
    editor_values = card_values.copy()
    renewal_report = build_valuation_renewal_report(editor_values)
    editor_values["freshness_status"] = renewal_report[
        "freshness_status"
    ].to_numpy()
    edited = st.data_editor(
        editor_values,
        num_rows="dynamic",
        width="stretch",
        disabled=["freshness_status"],
    )
    if st.button("Save Card Values"):
        try:
            validated_values = validate_valuation_frame(
                edited.drop(columns=["freshness_status"], errors="ignore")
            )
        except InputValidationError as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "CARD_VALUES_VALIDATION_FAILED",
                exc,
                "card_values.save.validate",
            )
            st.error(str(exc))
        else:
            try:
                save_valuation_frame_atomically(CARD_VALUES_PATH, validated_values)
            except Exception as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "CARD_VALUES_SAVE_FAILED",
                    exc,
                    "card_values.save.persist",
                )
                st.error("Card values could not be saved. See local diagnostics.")
            else:
                st.success("Card values saved.")

with setup_tab:
    st.markdown("""
### Run on macOS
```bash
cd ~/Projects/CardProfitHunter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
python -m streamlit run app.py
```
The database is created automatically at `data/card_profit_hunter.db`.
""")
    st.divider()
    st.subheader("Sanitized Application Diagnostics")
    st.caption(
        "This report includes application/runtime versions and configuration presence only. "
        "Credentials, tokens, filesystem paths, database contents, submitted values, and "
        "exception details are excluded. Local diagnostic logging status appears below; "
        "when enabled, logs are stored under output/logs/application.log."
    )
    st.json(startup_diagnostics)
    st.divider()
    st.subheader("Local Database Maintenance")
    st.caption(
        "Backups contain private local history and are stored under "
        "output/database_backups/. No cleanup runs automatically."
    )
    restore_notice = st.session_state.pop("database_restore_notice", None)
    if restore_notice:
        st.success(restore_notice)

    if st.button("Create Database Backup"):
        try:
            backup_path = create_database_backup(DATABASE_BACKUP_DIR)
        except DatabaseMaintenanceError as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "DATABASE_BACKUP_FAILED",
                exc,
                "database.backup.create",
            )
            st.error(str(exc))
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "DATABASE_BACKUP_FAILED",
                exc,
                "database.backup.create",
            )
            st.error("Database backup could not be created. See local diagnostics.")
        else:
            if backup_path is None:
                st.info("No local database is available to back up.")
            else:
                st.success(f"Database backup created: {backup_path.name}")

    st.markdown("#### Restore a Local Database Backup")
    st.warning(
        "Restoring replaces the current local database. CardProfitHunter creates a "
        "separate safety backup of the current database before replacement."
    )
    try:
        available_backups = sorted(
            (
                path
                for path in DATABASE_BACKUP_DIR.glob("*.db")
                if path.is_file() and not path.is_symlink()
            ),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError as exc:
        log_sanitized_exception(
            diagnostic_logger,
            "DATABASE_BACKUP_LIST_FAILED",
            exc,
            "database.backup.list",
        )
        available_backups = []
        st.error("Local database backups could not be listed. See local diagnostics.")

    if not available_backups:
        st.info("No local database backups are available to restore.")
    else:
        backup_names = [path.name for path in available_backups]
        selected_backup_name = st.selectbox(
            "Local database backup",
            backup_names,
        )
        selected_backup_path = DATABASE_BACKUP_DIR / selected_backup_name
        if st.button("Verify Selected Database Backup"):
            try:
                verified_backup = inspect_database_backup(
                    selected_backup_path,
                    DATABASE_BACKUP_DIR,
                )
            except DatabaseMaintenanceError as exc:
                st.session_state.pop("verified_database_backup", None)
                log_sanitized_exception(
                    diagnostic_logger,
                    "DATABASE_BACKUP_VERIFY_FAILED",
                    exc,
                    "database.backup.verify",
                )
                st.error(str(exc))
            except Exception as exc:
                st.session_state.pop("verified_database_backup", None)
                log_sanitized_exception(
                    diagnostic_logger,
                    "DATABASE_BACKUP_VERIFY_FAILED",
                    exc,
                    "database.backup.verify",
                )
                st.error("Database backup could not be verified. See local diagnostics.")
            else:
                st.session_state["verified_database_backup"] = selected_backup_name
                st.success(
                    "Backup verified: "
                    f"schema {verified_backup['schema_version']}, "
                    f"{verified_backup['size_bytes']} bytes."
                )

        selected_backup_verified = (
            st.session_state.get("verified_database_backup")
            == selected_backup_name
        )
        restore_confirmed = st.checkbox(
            "I understand that restore will replace the current local database."
        )
        restore_allowed = selected_backup_verified and restore_confirmed
        if st.button(
            "Restore Selected Database Backup",
            disabled=not restore_allowed,
        ):
            try:
                restore_database_backup(
                    selected_backup_path,
                    DATABASE_BACKUP_DIR,
                    confirmed=restore_confirmed,
                )
            except DatabaseMaintenanceError as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "DATABASE_RESTORE_FAILED",
                    exc,
                    "database.backup.restore",
                )
                st.error(str(exc))
            except Exception as exc:
                log_sanitized_exception(
                    diagnostic_logger,
                    "DATABASE_RESTORE_FAILED",
                    exc,
                    "database.backup.restore",
                )
                st.error("Database restore could not be completed. See local diagnostics.")
            else:
                for state_key in (
                    "daily_board",
                    "daily_board_outcome",
                    "last_results",
                    "live_search_outcome",
                    "live_search_diagnostics",
                    "verified_database_backup",
                ):
                    st.session_state.pop(state_key, None)
                st.session_state["database_restore_notice"] = (
                    "Database restored successfully. A pre-restore safety backup was created."
                )
                st.rerun()

    retention_days = st.number_input(
        "Keep search and opportunity history for at least this many days",
        min_value=30,
        value=365,
        step=30,
    )
    retention_cutoff = datetime.now(timezone.utc) - timedelta(
        days=int(retention_days)
    )
    if st.button("Preview History Cleanup"):
        try:
            preview = preview_history_retention(retention_cutoff)
        except DatabaseMaintenanceError as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "RETENTION_PREVIEW_FAILED",
                exc,
                "database.retention.preview",
            )
            st.error(str(exc))
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "RETENTION_PREVIEW_FAILED",
                exc,
                "database.retention.preview",
            )
            st.error("History cleanup preview could not be completed. See local diagnostics.")
        else:
            st.info(
                "Eligible for deletion: "
                f"{preview['search_runs']} search runs and "
                f"{preview['opportunity_snapshots']} opportunity snapshots, plus "
                f"{preview['opportunity_batches']} recorded batch outcomes."
            )

    retention_confirmed = st.checkbox(
        "I understand that old history will be backed up and then deleted."
    )
    if st.button(
        "Back Up and Delete Old History",
        disabled=not retention_confirmed,
    ):
        try:
            deleted = apply_history_retention(
                retention_cutoff,
                DATABASE_BACKUP_DIR,
                confirmed=retention_confirmed,
            )
        except DatabaseMaintenanceError as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "RETENTION_APPLY_FAILED",
                exc,
                "database.retention.apply",
            )
            st.error(str(exc))
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "RETENTION_APPLY_FAILED",
                exc,
                "database.retention.apply",
            )
            st.error("History cleanup could not be completed. See local diagnostics.")
        else:
            backup_path = deleted["backup_path"]
            st.success(
                f"Deleted {deleted['search_runs']} search runs and "
                f"{deleted['opportunity_snapshots']} opportunity snapshots, plus "
                f"{deleted['opportunity_batches']} recorded batch outcomes. "
                f"Backup created first: {backup_path.name}"
            )
