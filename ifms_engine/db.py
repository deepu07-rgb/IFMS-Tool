import sqlite3

def init_v2_schema(db_path):
    """
    Initialize the V2 database schema while preserving existing tables.
    """
    db = sqlite3.connect(db_path)
    
    db.executescript('''
    CREATE TABLE IF NOT EXISTS bills_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_filename TEXT,
        file_hash TEXT,
        sheet_type TEXT,
        group_name TEXT,
        month_year TEXT,
        reference_no TEXT,
        bill_no TEXT,
        bill_date TEXT,
        office_id TEXT,
        ddo_name TEXT,
        ddo_code TEXT,
        demand_no TEXT,
        object_head TEXT,
        budget_head_full TEXT,
        budget_major_head TEXT,
        budget_sub_major TEXT,
        budget_minor_head TEXT,
        budget_scheme TEXT,
        fund_type TEXT,
        voted_charged TEXT,
        sf_amount REAL DEFAULT 0,
        ca_amount REAL DEFAULT 0,
        na_amount REAL DEFAULT 0,
        tan_no TEXT,
        page_count INTEGER DEFAULT 0,
        bill_pattern TEXT,
        official_gross REAL DEFAULT 0,
        official_deduction REAL DEFAULT 0,
        official_net REAL DEFAULT 0,
        parsed_gross REAL DEFAULT 0,
        parsed_deduction REAL DEFAULT 0,
        parsed_net REAL DEFAULT 0,
        verification_status TEXT DEFAULT '',
        warning_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employees_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER,
        source_filename TEXT,
        page_no INTEGER,
        sr_no INTEGER,
        group_name TEXT,
        month_year TEXT,
        raw_name TEXT,
        normalized_name TEXT,
        raw_designation TEXT,
        raw_designation_full TEXT,
        raw_designation_en TEXT,
        raw_designation_hi TEXT,
        raw_designation_key TEXT,
        normalized_designation TEXT,
        final_designation TEXT,
        final_designation_en TEXT,
        final_designation_hi TEXT,
        final_designation_hi_display TEXT,
        designation_display_language TEXT DEFAULT 'English',
        designation_category TEXT,
        designation_confidence REAL DEFAULT 0,
        designation_mapping_status TEXT,
        designation_source TEXT,
        designation_needs_review INTEGER DEFAULT 0,
        employee_data_status TEXT,
        gpf_pran_raw TEXT,
        dob TEXT,
        belt_no TEXT,
        pan_raw TEXT,
        pan_status TEXT,
        employee_id TEXT,
        st_ins_no TEXT,
        pay_scale_raw TEXT,
        grade_pay TEXT,
        bank_acc TEXT,
        aadhar_raw TEXT,
        gross_amount REAL DEFAULT 0,
        sum_deduction REAL DEFAULT 0,
        net_total REAL DEFAULT 0,
        calc_gross REAL DEFAULT 0,
        calc_deduction REAL DEFAULT 0,
        calc_net REAL DEFAULT 0,
        row_verification_status TEXT,
        raw_text_block TEXT,
        is_deleted INTEGER DEFAULT 0,
        deleted_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(bill_id) REFERENCES bills_v2(id)
    );

    CREATE TABLE IF NOT EXISTS employee_components_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        bill_id INTEGER,
        component_type TEXT,
        raw_head TEXT,
        normalized_head TEXT,
        amount REAL DEFAULT 0,
        included_in_total INTEGER DEFAULT 1,
        mapping_status TEXT,
        confidence REAL DEFAULT 0,
        source_type TEXT DEFAULT 'parsed',
        source_page INTEGER,
        source_y REAL,
        FOREIGN KEY(employee_id) REFERENCES employees_v2(id),
        FOREIGN KEY(bill_id) REFERENCES bills_v2(id)
    );

    CREATE TABLE IF NOT EXISTS validation_issues_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER,
        employee_id INTEGER,
        issue_type TEXT,
        severity TEXT,
        message TEXT,
        raw_value TEXT,
        suggested_value TEXT,
        status TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT,
        FOREIGN KEY(bill_id) REFERENCES bills_v2(id),
        FOREIGN KEY(employee_id) REFERENCES employees_v2(id)
    );

    CREATE TABLE IF NOT EXISTS dictionary_terms_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dictionary_type TEXT,
        raw_value TEXT,
        normalized_value TEXT,
        category TEXT,
        language TEXT,
        confidence REAL DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS dictionary_mappings_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        raw_text TEXT,
        raw_text_key TEXT,
        final_text TEXT,
        final_text_en TEXT,
        final_text_hi TEXT,
        match_type TEXT DEFAULT 'exact',
        priority INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS review_queue_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER,
        employee_id INTEGER,
        source_file TEXT,
        page_no INTEGER,
        sr_no INTEGER,
        employee_name TEXT,
        employee_id_text TEXT,
        field_name TEXT,
        raw_value TEXT,
        suggested_value TEXT,
        confidence REAL DEFAULT 0,
        issue_type TEXT,
        status TEXT DEFAULT 'OPEN',
        action TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT,
        FOREIGN KEY(bill_id) REFERENCES bills_v2(id),
        FOREIGN KEY(employee_id) REFERENCES employees_v2(id)
    );

    CREATE TABLE IF NOT EXISTS edit_audit_log_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        action_type TEXT,
        table_name TEXT,
        record_id INTEGER,
        field_name TEXT,
        old_value TEXT,
        new_value TEXT,
        source_file TEXT,
        page_no INTEGER,
        sr_no INTEGER,
        employee_name TEXT,
        employee_id TEXT,
        applied_scope TEXT,
        user_note TEXT
    );

    CREATE TABLE IF NOT EXISTS edit_audit_log_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT,
        record_id INTEGER,
        field_name TEXT,
        old_value TEXT,
        new_value TEXT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS upload_jobs_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_filename TEXT,
        status TEXT,
        total_pages INTEGER DEFAULT 0,
        processed_pages INTEGER DEFAULT 0,
        detected_employees INTEGER DEFAULT 0,
        started_at TEXT,
        finished_at TEXT,
        message TEXT,
        percent_complete REAL DEFAULT 0,
        review_issue_count INTEGER DEFAULT 0,
        error_message TEXT,
        current_stage TEXT DEFAULT 'queued',
        employees_saved INTEGER DEFAULT 0,
        issue_count INTEGER DEFAULT 0,
        warning_count INTEGER DEFAULT 0
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_bills_v2_group_name ON bills_v2(group_name);
    CREATE INDEX IF NOT EXISTS idx_bills_v2_month_year ON bills_v2(month_year);

    CREATE INDEX IF NOT EXISTS idx_employees_v2_bill_id ON employees_v2(bill_id);
    CREATE INDEX IF NOT EXISTS idx_employees_v2_employee_id ON employees_v2(employee_id);
    CREATE INDEX IF NOT EXISTS idx_employees_v2_group_name ON employees_v2(group_name);
    CREATE INDEX IF NOT EXISTS idx_employees_v2_month_year ON employees_v2(month_year);
    CREATE INDEX IF NOT EXISTS idx_employees_v2_norm_designation ON employees_v2(normalized_designation);
    CREATE INDEX IF NOT EXISTS idx_dict_v3_category_active ON dictionary_mappings_v3(category, active);
    CREATE INDEX IF NOT EXISTS idx_review_queue_v3_status ON review_queue_v3(status);
    CREATE INDEX IF NOT EXISTS idx_review_queue_v3_employee_id ON review_queue_v3(employee_id);

    CREATE INDEX IF NOT EXISTS idx_components_v2_employee_id ON employee_components_v2(employee_id);
    CREATE INDEX IF NOT EXISTS idx_components_v2_bill_id ON employee_components_v2(bill_id);
    CREATE INDEX IF NOT EXISTS idx_components_v2_comp_type ON employee_components_v2(component_type);
    CREATE INDEX IF NOT EXISTS idx_components_v2_norm_head ON employee_components_v2(normalized_head);

    CREATE INDEX IF NOT EXISTS idx_issues_v2_bill_id ON validation_issues_v2(bill_id);
    CREATE INDEX IF NOT EXISTS idx_issues_v2_employee_id ON validation_issues_v2(employee_id);
    CREATE INDEX IF NOT EXISTS idx_issues_v2_issue_type ON validation_issues_v2(issue_type);
    CREATE INDEX IF NOT EXISTS idx_issues_v2_status ON validation_issues_v2(status);
    ''')

    employee_cols = [row[1] for row in db.execute("PRAGMA table_info(employees_v2)").fetchall()]
    employee_migrations = {
        'raw_designation_full': 'TEXT',
        'raw_designation_en': 'TEXT',
        'raw_designation_hi': 'TEXT',
        'raw_designation_key': 'TEXT',
        'final_designation': 'TEXT',
        'final_designation_en': 'TEXT',
        'final_designation_hi': 'TEXT',
        'final_designation_hi_display': 'TEXT',
        'designation_display_language': "TEXT DEFAULT 'English'",
        'designation_source': 'TEXT',
        'designation_needs_review': 'INTEGER DEFAULT 0',
        'employee_data_status': 'TEXT',
        'is_deleted': 'INTEGER DEFAULT 0',
        'deleted_at': 'TEXT',
    }
    for col, typ in employee_migrations.items():
        if col not in employee_cols:
            db.execute(f'ALTER TABLE employees_v2 ADD COLUMN {col} {typ}')

    component_cols = [row[1] for row in db.execute("PRAGMA table_info(employee_components_v2)").fetchall()]
    component_migrations = {
        'source_type': "TEXT DEFAULT 'parsed'",
    }
    for col, typ in component_migrations.items():
        if col not in component_cols:
            db.execute(f'ALTER TABLE employee_components_v2 ADD COLUMN {col} {typ}')

    dict_cols = [row[1] for row in db.execute("PRAGMA table_info(dictionary_mappings_v3)").fetchall()]
    dict_migrations = {
        'raw_text_key': 'TEXT',
        'final_text': 'TEXT',
    }
    for col, typ in dict_migrations.items():
        if col not in dict_cols:
            db.execute(f'ALTER TABLE dictionary_mappings_v3 ADD COLUMN {col} {typ}')

    job_cols = [row[1] for row in db.execute("PRAGMA table_info(upload_jobs_v2)").fetchall()]
    job_migrations = {
        'percent_complete': 'REAL DEFAULT 0',
        'review_issue_count': 'INTEGER DEFAULT 0',
        'error_message': 'TEXT',
        'current_stage': "TEXT DEFAULT 'queued'",
        'employees_saved': 'INTEGER DEFAULT 0',
        'issue_count': 'INTEGER DEFAULT 0',
        'warning_count': 'INTEGER DEFAULT 0',
    }
    for col, typ in job_migrations.items():
        if col not in job_cols:
            db.execute(f'ALTER TABLE upload_jobs_v2 ADD COLUMN {col} {typ}')

    db.execute("""
        UPDATE employees_v2
        SET raw_designation_full = COALESCE(raw_designation_full, raw_designation),
            final_designation = COALESCE(NULLIF(final_designation, ''), NULLIF(final_designation_en, ''), normalized_designation),
            final_designation_en = COALESCE(NULLIF(final_designation_en, ''), normalized_designation),
            designation_display_language = COALESCE(NULLIF(designation_display_language, ''), 'English'),
            employee_data_status = COALESCE(NULLIF(employee_data_status, ''), row_verification_status)
    """)
    db.execute("""
        UPDATE dictionary_mappings_v3
        SET final_text = COALESCE(NULLIF(final_text, ''), final_text_en)
    """)
    try:
        from ifms_engine.dictionary import clean_designation_key, extract_designation_parts, extract_english_designation

        employee_rows = db.execute("""
            SELECT id, COALESCE(raw_designation_full, raw_designation, '') AS raw
            FROM employees_v2
            WHERE COALESCE(raw_designation_en, '') = ''
               OR COALESCE(raw_designation_hi, '') = ''
               OR COALESCE(raw_designation_key, '') = ''
               OR COALESCE(final_designation_hi_display, '') = ''
        """).fetchall()
        for row in employee_rows:
            parts = extract_designation_parts(row[1])
            raw_en = parts["raw_designation_en"] or extract_english_designation(row[1])
            db.execute("""
                UPDATE employees_v2
                SET raw_designation_en = ?,
                    raw_designation_hi = ?,
                    raw_designation_key = ?,
                    final_designation_hi_display = COALESCE(NULLIF(final_designation_hi_display, ''), ?)
                WHERE id = ?
            """, (
                raw_en,
                parts["raw_designation_hi"],
                clean_designation_key(raw_en),
                parts["raw_designation_hi"],
                row[0],
            ))

        dict_rows = db.execute("""
            SELECT id, COALESCE(raw_text, '') AS raw
            FROM dictionary_mappings_v3
            WHERE COALESCE(raw_text_key, '') = ''
        """).fetchall()
        for row in dict_rows:
            db.execute("""
                UPDATE dictionary_mappings_v3
                SET raw_text_key = ?
                WHERE id = ?
            """, (clean_designation_key(row[1]), row[0]))
    except Exception:
        pass
    db.execute("CREATE INDEX IF NOT EXISTS idx_employees_v2_final_designation_en ON employees_v2(final_designation_en)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_employees_v2_final_designation ON employees_v2(final_designation)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_employees_v2_raw_designation_key ON employees_v2(raw_designation_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_employees_v2_is_deleted ON employees_v2(is_deleted)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dict_v3_designation_key ON dictionary_mappings_v3(category, active, raw_text_key)")
    
    db.commit()
    db.close()
