from __future__ import annotations

import json
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
from csv_export_safety import dataframe_to_spreadsheet_safe_csv
from database import (
    DB_PATH, SCHEMA_VERSION, DatabaseMaintenanceError, add_watchlist_row, apply_history_retention,
    create_database_backup, dashboard_metrics, delete_saved_search, delete_watchlist_item, init_db,
    latest_batch_summary, latest_opportunities, latest_batch_metrics, latest_batch_opportunities,
    preview_history_retention, recent_activity, list_saved_searches, list_search_runs, list_watchlist,
    log_search_run, save_opportunity_batch, save_search,
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
    load_listing_csv,
    load_settings_file,
    load_valuation_csv,
    validate_search_inputs,
    validate_settings,
    validate_valuation_frame,
)
from profit_engine import analyze_listings
from search_workflows import (
    RunOutcome,
    build_run_outcome,
    clear_result_state,
    combine_board_results,
    empty_analysis_frame,
    stable_analysis_frame,
)

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "config" / "settings.json"
SAMPLE_LISTINGS_PATH = ROOT / "sample_data" / "sample_listings.csv"
CARD_VALUES_PATH = ROOT / "sample_data" / "card_values.csv"
OUTPUT_DIR = ROOT / "output"
DATABASE_BACKUP_DIR = OUTPUT_DIR / "database_backups"
DIAGNOSTIC_LOG_DIR = OUTPUT_DIR / "logs"
VERSION_PATH = ROOT / "VERSION"

st.set_page_config(page_title="Card Profit Hunter V5.1", page_icon="📈", layout="wide")
logger_setup = configure_local_logger(DIAGNOSTIC_LOG_DIR)
diagnostic_logger = logger_setup.logger


def load_settings() -> dict:
    return load_settings_file(SETTINGS_PATH)


def save_settings(settings: dict) -> None:
    validated = validate_settings(settings)
    SETTINGS_PATH.write_text(json.dumps(validated, indent=2), encoding="utf-8")


def save_output(df: pd.DataFrame, filename: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    dataframe_to_spreadsheet_safe_csv(df, path)
    return path


def valuation_data_warning(values: pd.DataFrame) -> None:
    if "notes" in values.columns and values["notes"].fillna("").str.contains("example only", case=False).any():
        st.error(
            "Bundled card values are demonstration data only. They are now blocked from generating "
            "BUY or OFFER recommendations. Replace them with verified sold-comparable values in the Card Values tab."
        )

def metrics_block(df: pd.DataFrame) -> None:
    if df.empty:
        st.warning("No results to display.")
        return
    counts = df["recommended_action"].value_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Buy Candidates", int(counts.get("BUY_RAW_FLIP", 0) + counts.get("BUY_GRADE_PSA", 0)))
    c2.metric("Offers", int(counts.get("OFFER", 0)))
    c3.metric("Watch", int(counts.get("WATCH", 0)))
    c4.metric("Pass", int(counts.get("PASS", 0)))
    c5.metric("Listings", len(df))


def result_table(df: pd.DataFrame) -> None:
    preferred = ["recommended_action", "total_score", "best_path", "best_expected_profit",
                 "best_expected_roi_pct", "suggested_offer", "total_price", "title",
                 "matched_card", "seller_username", "condition", "item_url", "flags"]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    st.dataframe(df[cols], width="stretch", hide_index=True)


def show_run_outcome(label: str, outcome: RunOutcome) -> None:
    if outcome.status == "success":
        st.success(f"{label} completed with {outcome.result_count} results.")
    elif outcome.status == "empty":
        st.info(f"{label} completed successfully but returned no listings.")
    elif outcome.status == "partial":
        st.warning(
            f"{label} partially completed: {outcome.successful_count} succeeded, "
            f"{outcome.failed_count} failed, and {outcome.result_count} results are current."
        )
    else:
        st.error(f"{label} failed: all attempted searches failed.")

    st.caption(f"Completed: {outcome.completed_at}")
    if outcome.errors:
        st.warning("Search failures:\n- " + "\n- ".join(outcome.errors))


st.title("Card Profit Hunter V5.1 Professional Edition")
st.caption("Executive Dashboard • Daily Buy Board • Live eBay sourcing • Opportunity history")
if logger_setup.warning:
    st.warning(logger_setup.warning)
try:
    startup_values = run_startup_steps((
        StartupStep(
            "environment",
            "STARTUP_ENVIRONMENT",
            "Local environment configuration could not be loaded.",
            lambda: load_dotenv(ROOT / ".env"),
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
    st.success("Credentials loaded locally.") if client_id and client_secret else st.info("Add credentials in .env or enter them here.")

    st.divider(); st.header("Profit Settings")
    fields = [
        ("ebay_fee_pct", "eBay fee %", 0.0, 0.30, 0.0025, "%.4f"),
        ("raw_flip_shipping_allowance", "Raw flip shipping/supplies", 0.0, None, 1.0, None),
        ("psa_grading_fee", "PSA grading fee", 0.0, None, 1.0, None),
        ("psa_shipping_insurance_allowance", "PSA shipping/insurance", 0.0, None, 1.0, None),
        ("psa_selling_shipping_allowance", "PSA sale shipping", 0.0, None, 1.0, None),
        ("minimum_raw_flip_profit", "Minimum raw profit", 0.0, None, 5.0, None),
        ("minimum_raw_flip_roi_pct", "Minimum raw ROI %", 0.0, None, 5.0, None),
        ("minimum_psa_expected_profit", "Minimum PSA profit", 0.0, None, 5.0, None),
        ("minimum_psa_expected_roi_pct", "Minimum PSA ROI %", 0.0, None, 5.0, None),
    ]
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

    p1, p2 = st.columns(2)
    with p1:
        st.markdown("#### Inventory Manager")
        st.info("Inventory and cost-basis tracking arrives in V5.2.")
    with p2:
        st.markdown("#### PSA Pipeline")
        st.info("Submission and grading workflow arrives in V5.3.")

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
                batch_id = uuid.uuid4().hex
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
                        successful_count += 1
                        if scored.empty:
                            empty_count += 1
                        else:
                            save_opportunity_batch(
                                batch_id,
                                int(row["id"]),
                                search_name,
                                validated_query,
                                scored,
                            )
                            combined.append(scored)
                        log_search_run(
                            validated_query,
                            len(scored),
                            int(row["id"]),
                        )
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
                    st.warning(
                        "Daily Buy Board results are available, but the local output file "
                        "could not be saved. See local diagnostics."
                    )

        outcome = st.session_state.get("daily_board_outcome")
        if isinstance(outcome, RunOutcome):
            show_run_outcome("Daily Buy Board", outcome)
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
    q = st.text_input("Search query", value=str(preset["query"]) if preset is not None else "Victor Wembanyama raw rookie prizm silver -PSA -BGS -SGC")
    c1, c2, c3, c4 = st.columns(4)
    limit = c1.number_input("Result limit", 1, 200, int(preset["limit_count"]) if preset is not None else 50, 10)
    sorts = ["newlyListed", "endingSoonest", "price", "-price"]
    sort = c2.selectbox("Sort", sorts, index=sorts.index(str(preset["sort_order"])) if preset is not None and str(preset["sort_order"]) in sorts else 0)
    max_price = c3.number_input("Max price", 0.0, value=float(preset["max_price"] or 1000) if preset is not None else 1000.0, step=50.0)
    category_ids = c4.text_input("Category IDs", value=str(preset["category_ids"] or "") if preset is not None else "")
    search_name = st.text_input("Saved search name", value=selected if selected != "New search" else "")
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
                    int(limit),
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
                with st.spinner("Searching eBay and scoring listings..."):
                    items = search_ebay(
                        credentials,
                        validated_query,
                        int(limit),
                        sort,
                        validated_category_ids,
                        max_price if max_price > 0 else None,
                    )
                    listings = normalize_ebay_items(items)
                    results = stable_analysis_frame(
                        analyze_listings(
                            listings,
                            card_values,
                            settings,
                        )
                    )
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
        show_run_outcome("Live Search", outcome)
    results = st.session_state.get("last_results")
    if isinstance(results, pd.DataFrame) and not results.empty:
        metrics_block(results); result_table(results)
        try:
            st.download_button(
                "Download Buy Board CSV",
                dataframe_to_spreadsheet_safe_csv(results).encode("utf-8"),
                "live_ebay_buy_board.csv",
                "text/csv",
            )
        except Exception as exc:
            log_sanitized_exception(
                diagnostic_logger,
                "LIVE_DOWNLOAD_PREPARE_FAILED",
                exc,
                "live_search.download.prepare",
            )
            st.error("Live Search CSV could not be prepared. See local diagnostics.")
        if not results.empty:
            labels = [f"{i}: {row.get('title','')[:90]}" for i, row in results.reset_index(drop=True).iterrows()]
            pick = st.selectbox("Add listing to watchlist", labels)
            notes = st.text_input("Watchlist notes")
            if st.button("Add Selected Listing"):
                idx = int(pick.split(":", 1)[0]); add_watchlist_row(results.reset_index(drop=True).iloc[idx].to_dict(), notes)
                st.success("Added to watchlist.")

with saved_tab:
    st.subheader("Saved Searches")
    df = list_saved_searches(); st.dataframe(df, width="stretch", hide_index=True)
    if not df.empty:
        delete_id = st.selectbox("Delete saved search", df["id"].tolist(), format_func=lambda x: df.loc[df.id == x, "name"].iloc[0])
        if st.button("Delete Search"): delete_saved_search(int(delete_id)); st.rerun()
    st.subheader("Recent Search Runs"); st.dataframe(list_search_runs(), width="stretch", hide_index=True)

with watch_tab:
    st.subheader("Watchlist")
    watch = list_watchlist(); st.dataframe(watch, width="stretch", hide_index=True)
    if not watch.empty:
        delete_id = st.selectbox("Remove watchlist item", watch["id"].tolist(), format_func=lambda x: watch.loc[watch.id == x, "title"].iloc[0][:100])
        if st.button("Remove Item"): delete_watchlist_item(int(delete_id)); st.rerun()
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
    listings_file = st.file_uploader("Listings CSV", type=["csv"])
    values_file = st.file_uploader("Card values CSV", type=["csv"])
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
    st.caption("Use exact card identifiers and verified sold comps. Rows marked 'Example only' are non-actionable by design.")
    edited = st.data_editor(card_values, num_rows="dynamic", width="stretch")
    if st.button("Save Card Values"):
        try:
            validated_values = validate_valuation_frame(edited)
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
                validated_values.to_csv(CARD_VALUES_PATH, index=False)
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
cp .env.example .env
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
                f"{preview['opportunity_snapshots']} opportunity snapshots."
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
                f"{deleted['opportunity_snapshots']} opportunity snapshots. "
                f"Backup created first: {backup_path.name}"
            )
