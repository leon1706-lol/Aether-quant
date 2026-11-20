# aether_quant.training

Training without the training stack: splits, purges, purged folds, yearly windows, ranked inputs, the walk-forward linear model, signal recipes, and what the models could know. Also training on a small machine (V6.6.10): memory profiles and their estimate, lazy sequence windows, a float32 chunked reader and the process's peak memory, and resumable runs: a run folder with its record and finished steps, the run to continue, and the list of runs.

::: aether_quant.training
    options:
      members:
        - MemoryProfile
        - annual_windows
        - assign_split
        - assign_split_series
        - audit_trial_ids
        - build_table
        - centred_label
        - done_steps
        - estimate_peak_gb
        - fama_macbeth_ridge
        - feature_group_ic
        - find_resumable
        - fundamental_coverage
        - gather_windows
        - group_table
        - is_finished
        - list_runs
        - log_peak
        - mark_done
        - memory_profile
        - monthly_slope
        - process_memory_mb
        - profile_summary
        - purge_label_overlap
        - purge_label_overlap_calendar
        - purged_embargoed_folds
        - rank_inputs
        - read_csv_float32
        - render_runs
        - residualise_signal
        - sequence_window_index
        - start_record
        - update_record
