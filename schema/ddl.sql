-- Fabric & Ladies-Suit ERP — Production DDL
-- Postgres 16 | Multi-tenant with RLS | UUID PKs | Envelope encryption for PII
-- Architecture: §4 (tenancy), §5 (domain), §17 (entity specs)

-- Enable extensions
-- pgcrypto provides gen_random_uuid() which every PK default uses.
-- uuid-ossp is NOT required (removed per review P0-1 — was also invalid syntax without quotes).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- 1. ENUMS (states, statuses, types)
-- =============================================================================

CREATE TYPE voucher_status AS ENUM ('DRAFT', 'POSTED', 'RECONCILED', 'VOIDED');
CREATE TYPE challan_status AS ENUM ('DRAFT', 'ISSUED', 'ACKNOWLEDGED', 'IN_PROCESS', 'RETURNED', 'CLOSED');
CREATE TYPE mo_status AS ENUM ('DRAFT', 'RELEASED', 'IN_PROGRESS', 'COMPLETED', 'CLOSED');
CREATE TYPE qc_status AS ENUM ('PENDING', 'PASSED', 'FAILED', 'PARTIAL');
CREATE TYPE purchase_order_status AS ENUM ('DRAFT', 'APPROVED', 'CONFIRMED', 'PARTIAL_GRN', 'FULLY_RECEIVED', 'CANCELLED');
CREATE TYPE sales_order_status AS ENUM ('DRAFT', 'CONFIRMED', 'PARTIAL_DC', 'FULLY_DISPATCHED', 'INVOICED', 'CANCELLED');
CREATE TYPE quote_status AS ENUM ('DRAFT', 'SENT', 'NEGOTIATING', 'WON', 'LOST', 'EXPIRED', 'CONVERTED');
CREATE TYPE tax_status AS ENUM ('REGULAR', 'COMPOSITION', 'UNREGISTERED', 'CONSUMER', 'OVERSEAS');
CREATE TYPE party_type AS ENUM ('SUPPLIER', 'CUSTOMER', 'KARIGAR', 'TRANSPORTER', 'OTHER');
CREATE TYPE item_type AS ENUM ('RAW', 'SEMI_FINISHED', 'FINISHED', 'SERVICE', 'CONSUMABLE', 'BY_PRODUCT', 'SCRAP');
CREATE TYPE tracking_type AS ENUM ('NONE', 'BATCH', 'LOT', 'SERIAL');
CREATE TYPE uom_type AS ENUM ('METER', 'PIECE', 'KG', 'LITER', 'SET', 'GROSS', 'DOZEN', 'ROLL', 'BUNDLE', 'OTHER');
CREATE TYPE location_type AS ENUM ('WAREHOUSE', 'GODOWN', 'SHELF', 'BIN', 'IN_TRANSIT', 'STAGING', 'SCRAP');
CREATE TYPE mo_type AS ENUM ('SAMPLE', 'PRE_PRODUCTION', 'BULK', 'REWORK');
CREATE TYPE operation_type AS ENUM ('WEAVING', 'DYEING', 'EMBROIDERY', 'STITCHING', 'QC', 'PACKING', 'OTHER');
CREATE TYPE routing_edge_type AS ENUM ('FINISH_TO_START', 'START_TO_START', 'PARTIAL_FINISH_TO_START');
CREATE TYPE qc_sampling AS ENUM ('ONE_HUNDRED_PCT', 'AQL');
CREATE TYPE disposition_type AS ENUM ('ACCEPT', 'REWORK', 'SCRAP', 'DOWNGRADE', 'HOLD');
CREATE TYPE voucher_type AS ENUM ('SALES_INVOICE', 'PURCHASE_INVOICE', 'PAYMENT', 'RECEIPT', 'JOURNAL', 'CONTRA', 'DEBIT_NOTE', 'CREDIT_NOTE', 'OPENING_BAL');
CREATE TYPE payment_mode AS ENUM ('CASH', 'BANK_TRANSFER', 'CHEQUE', 'UPI', 'CREDIT', 'NEFT', 'RTGS', 'DD', 'CARD');
CREATE TYPE journal_line_type AS ENUM ('DR', 'CR');
CREATE TYPE bank_txn_type AS ENUM ('DEPOSIT', 'WITHDRAWAL', 'CHEQUE', 'TRANSFER', 'INTEREST', 'CHARGES', 'OTHER');
CREATE TYPE cheque_status AS ENUM ('ISSUED', 'CLEARED', 'BOUNCED', 'POST_DATED', 'STOPPED', 'CANCELLED');
CREATE TYPE rcm_status AS ENUM ('PROPOSED', 'CONFIRMED', 'REVERSED');
CREATE TYPE inter_firm_relationship_type AS ENUM ('TAX_INVOICE', 'BRANCH_TRANSFER', 'STOCK_JOURNAL');
CREATE TYPE job_work_status AS ENUM ('DRAFT', 'ISSUED', 'ACKNOWLEDGED', 'RETURNED', 'INVOICED', 'CLOSED');
CREATE TYPE cost_centre_type AS ENUM ('OUTLET', 'CHANNEL', 'SEASON', 'DESIGNER', 'SALESPERSON', 'DEPARTMENT');
CREATE TYPE eway_status AS ENUM ('DRAFT', 'GENERATED', 'CANCELLED', 'EXPIRED');
CREATE TYPE irn_status AS ENUM ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED');
CREATE TYPE supply_classification AS ENUM ('SIMPLE', 'COMPOSITE_PRINCIPAL', 'COMPOSITE_ANCILLARY', 'MIXED');
CREATE TYPE feature_flag_status AS ENUM ('OFF', 'ON', 'BETA', 'ROLLOUT');
CREATE TYPE plan_type AS ENUM ('STARTER', 'PROFESSIONAL', 'ENTERPRISE');
CREATE TYPE subscription_status AS ENUM ('TRIAL', 'ACTIVE', 'SUSPENDED', 'CANCELLED');
CREATE TYPE notification_type AS ENUM ('INFO', 'WARN', 'ERROR', 'TASK');
CREATE TYPE outbound_message_status AS ENUM ('DRAFT', 'QUEUED', 'SENT', 'FAILED', 'RETRYING', 'DEAD_LETTER');

-- =============================================================================
-- 2. IDENTITY & PLATFORM (Organization, Firm, User, Role, Permission, Auth)
-- =============================================================================

CREATE TABLE organization (
    org_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    legal_name VARCHAR(255),
    admin_email VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    country VARCHAR(2) DEFAULT 'IN',
    state_code VARCHAR(2),
    timezone VARCHAR(50) DEFAULT 'Asia/Kolkata',
    logo_url TEXT,
    has_foreign_txns BOOLEAN DEFAULT FALSE,
    is_exporter BOOLEAN DEFAULT FALSE,
    feature_flags JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    deleted_at TIMESTAMPTZ,
    prev_hash BYTEA,
    this_hash BYTEA
);
CREATE INDEX idx_organization_admin_email ON organization(admin_email);
CREATE INDEX idx_organization_deleted ON organization(deleted_at);

CREATE TABLE firm (
    firm_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    code VARCHAR(10) NOT NULL,
    name VARCHAR(255) NOT NULL,
    legal_name VARCHAR(255),
    gst_registration_type VARCHAR(50),
    gstin BYTEA,
    gstin_status VARCHAR(50),
    pan BYTEA,
    cin BYTEA,
    state_code VARCHAR(2),
    address TEXT,
    city VARCHAR(100),
    pincode VARCHAR(10),
    tan BYTEA,
    email VARCHAR(255),
    phone VARCHAR(20),
    fy_start_month SMALLINT DEFAULT 4,
    primary_godown_id UUID,
    financial_year_close_date DATE,
    invoicing_mode VARCHAR(20) DEFAULT 'PER_DISPATCH',
    has_gst BOOLEAN NOT NULL DEFAULT TRUE,
    is_sez BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    deleted_at TIMESTAMPTZ,
    prev_hash BYTEA,
    this_hash BYTEA,
    UNIQUE (org_id, code)
);
CREATE INDEX idx_firm_org ON firm(org_id);
CREATE INDEX idx_firm_deleted ON firm(deleted_at);
ALTER TABLE firm ENABLE ROW LEVEL SECURITY;
CREATE POLICY firm_rls ON firm USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE app_user (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    email VARCHAR(255) NOT NULL,
    legal_name VARCHAR(255),
    phone BYTEA,
    password_hash VARCHAR(255),
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret BYTEA,
    last_login_at TIMESTAMPTZ,
    last_login_ip VARCHAR(45),
    is_active BOOLEAN DEFAULT TRUE,
    is_suspended BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    deleted_at TIMESTAMPTZ,
    prev_hash BYTEA,
    this_hash BYTEA,
    UNIQUE (org_id, email)
);
CREATE INDEX idx_app_user_org_email ON app_user(org_id, email);
CREATE INDEX idx_app_user_deleted ON app_user(deleted_at);
ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;
CREATE POLICY app_user_rls ON app_user USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE role (
    role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_system_role BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,
    deleted_at TIMESTAMPTZ,
    UNIQUE (org_id, code)
);
CREATE INDEX idx_role_org ON role(org_id);
ALTER TABLE role ENABLE ROW LEVEL SECURITY;
CREATE POLICY role_rls ON role USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE permission (
    permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    resource VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    description TEXT,
    is_system_permission BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, resource, action)
);
CREATE INDEX idx_permission_org ON permission(org_id);
ALTER TABLE permission ENABLE ROW LEVEL SECURITY;
CREATE POLICY permission_rls ON permission USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE role_permission (
    role_permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    role_id UUID NOT NULL REFERENCES role(role_id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permission(permission_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role_id, permission_id)
);
CREATE INDEX idx_role_permission_role ON role_permission(role_id);
CREATE INDEX idx_role_permission_permission ON role_permission(permission_id);
ALTER TABLE role_permission ENABLE ROW LEVEL SECURITY;
CREATE POLICY role_permission_rls ON role_permission USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE user_role (
    user_role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES role(role_id) ON DELETE CASCADE,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Postgres disallows expressions inside an inline UNIQUE constraint; the
-- semantically correct uniqueness — one (user, role, firm) tuple where a
-- NULL firm_id is treated as the org-level scope — must be expressed as a
-- UNIQUE INDEX with COALESCE.
CREATE UNIQUE INDEX uq_user_role_user_role_firm
    ON user_role(user_id, role_id, COALESCE(firm_id, '00000000-0000-0000-0000-000000000000'::uuid));
CREATE INDEX idx_user_role_user ON user_role(user_id);
CREATE INDEX idx_user_role_role ON user_role(role_id);
CREATE INDEX idx_user_role_firm ON user_role(firm_id);
ALTER TABLE user_role ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_role_rls ON user_role USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE user_firm_scope (
    user_firm_scope_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, firm_id)
);
CREATE INDEX idx_user_firm_scope_user ON user_firm_scope(user_id);
CREATE INDEX idx_user_firm_scope_firm ON user_firm_scope(firm_id);
ALTER TABLE user_firm_scope ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_firm_scope_rls ON user_firm_scope USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE device (
    device_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    device_public_key BYTEA NOT NULL,
    device_name VARCHAR(255),
    device_type VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_device_user ON device(user_id);
CREATE INDEX idx_device_active ON device(is_active);
ALTER TABLE device ENABLE ROW LEVEL SECURITY;
CREATE POLICY device_rls ON device USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE session (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    device_id UUID REFERENCES device(device_id) ON DELETE SET NULL,
    access_token_hash VARCHAR(255) NOT NULL UNIQUE,
    refresh_token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_session_user ON session(user_id);
CREATE INDEX idx_session_expires ON session(expires_at);
CREATE INDEX idx_session_revoked ON session(revoked_at);
ALTER TABLE session ENABLE ROW LEVEL SECURITY;
CREATE POLICY session_rls ON session USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE audit_log (
    audit_log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE SET NULL,
    user_id UUID REFERENCES app_user(user_id) ON DELETE SET NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,
    changes JSONB,
    reason TEXT,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_hash BYTEA,
    this_hash BYTEA
);
CREATE INDEX idx_audit_log_org ON audit_log(org_id);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at DESC);
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_log_rls ON audit_log USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 3. MASTERS (Party, Item, SKU, UOM, HSN, COA, Ledger, Price List, Cost Centre)
-- =============================================================================

CREATE TABLE party (
    party_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    legal_name VARCHAR(255),
    party_type VARCHAR(50),
    is_supplier BOOLEAN DEFAULT FALSE,
    is_customer BOOLEAN DEFAULT FALSE,
    is_karigar BOOLEAN DEFAULT FALSE,
    is_transporter BOOLEAN DEFAULT FALSE,
    tax_status tax_status NOT NULL DEFAULT 'UNREGISTERED',
    gstin BYTEA,
    pan BYTEA,
    aadhaar_last_4 BYTEA,
    state_code VARCHAR(2),
    contact_person VARCHAR(255),
    email VARCHAR(255),
    phone BYTEA,
    is_sez BOOLEAN DEFAULT FALSE,
    is_export BOOLEAN DEFAULT FALSE,
    account_owner_id UUID REFERENCES app_user(user_id) ON DELETE SET NULL,
    credit_days SMALLINT DEFAULT 0,
    credit_limit NUMERIC(15,2) DEFAULT 0,
    charge_overdue_interest BOOLEAN DEFAULT TRUE,
    price_list_id UUID,
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES app_user(user_id),
    updated_by UUID REFERENCES app_user(user_id),
    deleted_at TIMESTAMPTZ,
    prev_hash BYTEA,
    this_hash BYTEA,
    UNIQUE (org_id, firm_id, code)
);
CREATE INDEX idx_party_org_firm ON party(org_id, firm_id);
CREATE INDEX idx_party_type ON party(is_supplier, is_customer, is_karigar);
CREATE INDEX idx_party_active ON party(is_active);
CREATE INDEX idx_party_deleted ON party(deleted_at);
ALTER TABLE party ENABLE ROW LEVEL SECURITY;
CREATE POLICY party_rls ON party USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE party_address (
    party_address_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE CASCADE,
    address_type VARCHAR(50),
    address_line_1 TEXT NOT NULL,
    address_line_2 TEXT,
    city VARCHAR(100),
    state_code VARCHAR(2),
    pincode VARCHAR(10),
    country VARCHAR(2) DEFAULT 'IN',
    is_primary BOOLEAN DEFAULT FALSE,
    latitude NUMERIC(10,8),
    longitude NUMERIC(11,8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_party_address_party ON party_address(party_id);
ALTER TABLE party_address ENABLE ROW LEVEL SECURITY;
CREATE POLICY party_address_rls ON party_address USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE party_bank (
    party_bank_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE CASCADE,
    bank_name VARCHAR(255),
    account_holder_name VARCHAR(255),
    account_number BYTEA,
    ifsc_code VARCHAR(11),
    branch VARCHAR(100),
    account_type VARCHAR(50),
    is_primary BOOLEAN DEFAULT FALSE,
    upi_id BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_party_bank_party ON party_bank(party_id);
ALTER TABLE party_bank ENABLE ROW LEVEL SECURITY;
CREATE POLICY party_bank_rls ON party_bank USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE party_kyc (
    party_kyc_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE CASCADE,
    kyc_status VARCHAR(50),
    gstin_verified_at TIMESTAMPTZ,
    pan_verified_at TIMESTAMPTZ,
    bank_verified_at TIMESTAMPTZ,
    msme_udyam_number BYTEA,
    last_kyc_refresh_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_party_kyc_party ON party_kyc(party_id);
ALTER TABLE party_kyc ENABLE ROW LEVEL SECURITY;
CREATE POLICY party_kyc_rls ON party_kyc USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE item (
    item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    item_type item_type NOT NULL,
    category VARCHAR(100),
    description TEXT,
    primary_uom uom_type NOT NULL,
    tracking tracking_type DEFAULT 'NONE',
    has_variants BOOLEAN DEFAULT FALSE,
    parent_item_id UUID REFERENCES item(item_id) ON DELETE SET NULL,
    variant_axes JSONB,
    hsn_code VARCHAR(8),
    gst_rate NUMERIC(5,2),
    supply_classification supply_classification DEFAULT 'SIMPLE',
    has_expiry BOOLEAN DEFAULT FALSE,
    allow_negative VARCHAR(50) DEFAULT 'NEVER',
    attributes JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES app_user(user_id),
    updated_by UUID REFERENCES app_user(user_id),
    deleted_at TIMESTAMPTZ,
    prev_hash BYTEA,
    this_hash BYTEA,
    UNIQUE (org_id, firm_id, code)
);
CREATE INDEX idx_item_org_firm ON item(org_id, firm_id);
CREATE INDEX idx_item_type ON item(item_type);
CREATE INDEX idx_item_parent ON item(parent_item_id);
CREATE INDEX idx_item_active ON item(is_active);
ALTER TABLE item ENABLE ROW LEVEL SECURITY;
CREATE POLICY item_rls ON item USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE sku (
    sku_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE CASCADE,
    code VARCHAR(50) NOT NULL,
    variant_attributes JSONB,
    barcode_ean13 VARCHAR(13),
    default_cost NUMERIC(15,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, code)
);
CREATE INDEX idx_sku_org_firm ON sku(org_id, firm_id);
CREATE INDEX idx_sku_item ON sku(item_id);
ALTER TABLE sku ENABLE ROW LEVEL SECURITY;
CREATE POLICY sku_rls ON sku USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE uom (
    uom_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    code VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    uom_type uom_type NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_uom_org ON uom(org_id);

CREATE TABLE item_uom_alt (
    item_uom_alt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE CASCADE,
    from_uom uom_type NOT NULL,
    to_uom uom_type NOT NULL,
    conversion_factor NUMERIC(15,6) NOT NULL,
    is_fixed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_id, from_uom, to_uom)
);
CREATE INDEX idx_item_uom_alt_item ON item_uom_alt(item_id);
ALTER TABLE item_uom_alt ENABLE ROW LEVEL SECURITY;
CREATE POLICY item_uom_alt_rls ON item_uom_alt USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE hsn (
    hsn_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    hsn_code VARCHAR(8) NOT NULL UNIQUE,
    description TEXT,
    gst_rate NUMERIC(5,2),
    is_rcm_applicable BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_hsn_org ON hsn(org_id);

CREATE TABLE coa_group (
    coa_group_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    group_type VARCHAR(50),
    parent_group_id UUID REFERENCES coa_group(coa_group_id) ON DELETE RESTRICT,
    is_system_group BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, code)
);
CREATE INDEX idx_coa_group_org ON coa_group(org_id);
ALTER TABLE coa_group ENABLE ROW LEVEL SECURITY;
CREATE POLICY coa_group_rls ON coa_group USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE ledger (
    ledger_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ledger_type VARCHAR(50),
    coa_group_id UUID NOT NULL REFERENCES coa_group(coa_group_id) ON DELETE RESTRICT,
    is_control_account BOOLEAN DEFAULT FALSE,
    party_id UUID REFERENCES party(party_id) ON DELETE SET NULL,
    bank_account_id UUID,
    opening_balance NUMERIC(15,2) DEFAULT 0,
    opening_balance_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES app_user(user_id),
    updated_by UUID REFERENCES app_user(user_id),
    deleted_at TIMESTAMPTZ,
    UNIQUE (org_id, firm_id, code)
);
CREATE INDEX idx_ledger_org_firm ON ledger(org_id, firm_id);
CREATE INDEX idx_ledger_group ON ledger(coa_group_id);
CREATE INDEX idx_ledger_party ON ledger(party_id);
ALTER TABLE ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY ledger_rls ON ledger USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE price_list (
    price_list_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    valid_from DATE,
    valid_to DATE,
    is_party_specific BOOLEAN DEFAULT FALSE,
    party_id UUID REFERENCES party(party_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, code)
);
CREATE INDEX idx_price_list_org_firm ON price_list(org_id, firm_id);
CREATE INDEX idx_price_list_party ON price_list(party_id);
ALTER TABLE price_list ENABLE ROW LEVEL SECURITY;
CREATE POLICY price_list_rls ON price_list USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE price_list_line (
    price_list_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    price_list_id UUID NOT NULL REFERENCES price_list(price_list_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    sku_id UUID REFERENCES sku(sku_id) ON DELETE SET NULL,
    selling_price NUMERIC(15,4) NOT NULL,
    min_qty NUMERIC(15,4) DEFAULT 0,
    currency VARCHAR(3) DEFAULT 'INR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_price_list_line_list ON price_list_line(price_list_id);
CREATE INDEX idx_price_list_line_item ON price_list_line(item_id);
ALTER TABLE price_list_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY price_list_line_rls ON price_list_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE cost_centre (
    cost_centre_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    cost_centre_type cost_centre_type,
    parent_cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_cost_centre_firm ON cost_centre(firm_id);
ALTER TABLE cost_centre ENABLE ROW LEVEL SECURITY;
CREATE POLICY cost_centre_rls ON cost_centre USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 4. INVENTORY (Lot, Location, Stock Ledger, Stock Position, Stock Take, Adjustments)
-- =============================================================================

CREATE TABLE lot (
    lot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_number VARCHAR(100) NOT NULL,
    supplier_lot_number VARCHAR(100),
    mfg_date DATE,
    expiry_date DATE,
    received_date DATE,
    weight_kg NUMERIC(15,4),
    measured_length_m NUMERIC(15,4),
    cost_basis VARCHAR(50),
    primary_cost NUMERIC(15,6),
    currency VARCHAR(3) DEFAULT 'INR',
    grn_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_hash BYTEA,
    this_hash BYTEA,
    UNIQUE (org_id, firm_id, item_id, lot_number)
);
CREATE INDEX idx_lot_org_firm_item ON lot(org_id, firm_id, item_id);
CREATE INDEX idx_lot_grn ON lot(grn_id);
ALTER TABLE lot ENABLE ROW LEVEL SECURITY;
CREATE POLICY lot_rls ON lot USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE location (
    location_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    location_type location_type NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_location_firm ON location(firm_id);
CREATE INDEX idx_location_type ON location(location_type);
ALTER TABLE location ENABLE ROW LEVEL SECURITY;
CREATE POLICY location_rls ON location USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE stock_ledger (
    stock_ledger_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE RESTRICT,
    location_id UUID NOT NULL REFERENCES location(location_id) ON DELETE RESTRICT,
    txn_type VARCHAR(50) NOT NULL,
    txn_date DATE NOT NULL,
    reference_type VARCHAR(50),
    reference_id UUID,
    qty_in NUMERIC(15,4) DEFAULT 0,
    qty_out NUMERIC(15,4) DEFAULT 0,
    unit_cost NUMERIC(15,6),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_hash BYTEA,
    this_hash BYTEA
);
CREATE INDEX idx_stock_ledger_org_firm ON stock_ledger(org_id, firm_id);
CREATE INDEX idx_stock_ledger_item_lot ON stock_ledger(item_id, lot_id);
CREATE INDEX idx_stock_ledger_location ON stock_ledger(location_id);
CREATE INDEX idx_stock_ledger_txn_date ON stock_ledger(txn_date);
ALTER TABLE stock_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_ledger_rls ON stock_ledger USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE stock_position (
    stock_position_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL,
    item_id UUID NOT NULL,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE CASCADE,
    location_id UUID NOT NULL,
    on_hand_qty NUMERIC(15,4) NOT NULL DEFAULT 0,
    reserved_qty_mo NUMERIC(15,4) DEFAULT 0,
    reserved_qty_so NUMERIC(15,4) DEFAULT 0,
    in_transit_qty NUMERIC(15,4) DEFAULT 0,
    atp_qty NUMERIC(15,4) GENERATED ALWAYS AS (
        on_hand_qty - reserved_qty_mo - reserved_qty_so - in_transit_qty
    ) STORED,
    current_cost NUMERIC(15,6),
    as_of_date DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Postgres disallows expressions inside an inline UNIQUE constraint; the
-- semantically correct uniqueness — one row per (org, firm, item, lot, location)
-- where NULL lot_id is treated as the no-lot sentinel — must be a UNIQUE INDEX.
CREATE UNIQUE INDEX uq_stock_position_org_firm_item_lot_location
    ON stock_position(
        org_id, firm_id, item_id,
        COALESCE(lot_id, '00000000-0000-0000-0000-000000000000'::uuid),
        location_id
    );
CREATE INDEX idx_stock_position_org_firm ON stock_position(org_id, firm_id);
CREATE INDEX idx_stock_position_atp ON stock_position(atp_qty);
ALTER TABLE stock_position ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_position_rls ON stock_position USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE stock_take (
    stock_take_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    location_id UUID NOT NULL REFERENCES location(location_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    scheduled_date DATE,
    start_date DATE,
    end_date DATE,
    status VARCHAR(50),
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    approved_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_stock_take_firm_location ON stock_take(firm_id, location_id);
CREATE INDEX idx_stock_take_status ON stock_take(status);
ALTER TABLE stock_take ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_take_rls ON stock_take USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE stock_take_line (
    stock_take_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    stock_take_id UUID NOT NULL REFERENCES stock_take(stock_take_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE SET NULL,
    system_qty NUMERIC(15,4),
    counted_qty NUMERIC(15,4),
    variance_qty NUMERIC(15,4),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_stock_take_line_take ON stock_take_line(stock_take_id);
CREATE INDEX idx_stock_take_line_item ON stock_take_line(item_id);
ALTER TABLE stock_take_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_take_line_rls ON stock_take_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE stock_adjustment (
    stock_adjustment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE RESTRICT,
    location_id UUID NOT NULL REFERENCES location(location_id) ON DELETE RESTRICT,
    qty_change NUMERIC(15,4) NOT NULL,
    reason VARCHAR(255),
    requires_approval BOOLEAN DEFAULT FALSE,
    approved_by UUID REFERENCES app_user(user_id),
    approved_at TIMESTAMPTZ,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_stock_adjustment_firm ON stock_adjustment(firm_id);
CREATE INDEX idx_stock_adjustment_item ON stock_adjustment(item_id);
ALTER TABLE stock_adjustment ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_adjustment_rls ON stock_adjustment USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE consignment_shipment (
    consignment_shipment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    shipment_date DATE NOT NULL,
    return_date DATE,
    status VARCHAR(50),
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_consignment_shipment_firm_party ON consignment_shipment(firm_id, party_id);
ALTER TABLE consignment_shipment ENABLE ROW LEVEL SECURITY;
CREATE POLICY consignment_shipment_rls ON consignment_shipment USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 5. PROCUREMENT (PO, GRN, Purchase Invoice, Returns, Landed Cost)
-- =============================================================================

CREATE TABLE purchase_order (
    purchase_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    po_date DATE NOT NULL,
    delivery_date DATE,
    status purchase_order_status DEFAULT 'DRAFT',
    total_amount NUMERIC(15,2),
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_po_org_firm ON purchase_order(org_id, firm_id);
CREATE INDEX idx_po_party ON purchase_order(party_id);
CREATE INDEX idx_po_status ON purchase_order(status);
ALTER TABLE purchase_order ENABLE ROW LEVEL SECURITY;
CREATE POLICY purchase_order_rls ON purchase_order USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE po_line (
    po_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    purchase_order_id UUID NOT NULL REFERENCES purchase_order(purchase_order_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty_ordered NUMERIC(15,4) NOT NULL,
    qty_received NUMERIC(15,4) DEFAULT 0,
    rate NUMERIC(15,4) NOT NULL,
    line_amount NUMERIC(15,2),
    taxes_applicable JSONB,
    line_sequence SMALLINT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_po_line_po ON po_line(purchase_order_id);
CREATE INDEX idx_po_line_item ON po_line(item_id);
ALTER TABLE po_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY po_line_rls ON po_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE grn (
    grn_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    purchase_order_id UUID REFERENCES purchase_order(purchase_order_id) ON DELETE SET NULL,
    grn_date DATE NOT NULL,
    status VARCHAR(50) DEFAULT 'DRAFT',
    total_qty_received NUMERIC(15,4),
    total_amount NUMERIC(15,2),
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_grn_org_firm ON grn(org_id, firm_id);
CREATE INDEX idx_grn_party ON grn(party_id);
CREATE INDEX idx_grn_po ON grn(purchase_order_id);
ALTER TABLE grn ENABLE ROW LEVEL SECURITY;
CREATE POLICY grn_rls ON grn USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE grn_line (
    grn_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    grn_id UUID NOT NULL REFERENCES grn(grn_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty_received NUMERIC(15,4) NOT NULL,
    weight_kg NUMERIC(15,4),
    measured_length_m NUMERIC(15,4),
    lot_number VARCHAR(100),
    rate NUMERIC(15,4),
    line_sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_grn_line_grn ON grn_line(grn_id);
CREATE INDEX idx_grn_line_item ON grn_line(item_id);
ALTER TABLE grn_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY grn_line_rls ON grn_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE purchase_invoice (
    purchase_invoice_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    grn_id UUID REFERENCES grn(grn_id) ON DELETE SET NULL,
    invoice_date DATE NOT NULL,
    invoice_amount NUMERIC(15,2),
    gst_amount NUMERIC(15,2),
    rcm_applicable BOOLEAN DEFAULT FALSE,
    status voucher_status DEFAULT 'DRAFT',
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_purchase_invoice_org_firm ON purchase_invoice(org_id, firm_id);
CREATE INDEX idx_purchase_invoice_party ON purchase_invoice(party_id);
CREATE INDEX idx_purchase_invoice_grn ON purchase_invoice(grn_id);
ALTER TABLE purchase_invoice ENABLE ROW LEVEL SECURITY;
CREATE POLICY purchase_invoice_rls ON purchase_invoice USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE pi_line (
    pi_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    purchase_invoice_id UUID NOT NULL REFERENCES purchase_invoice(purchase_invoice_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty NUMERIC(15,4),
    rate NUMERIC(15,4),
    line_amount NUMERIC(15,2),
    gst_rate NUMERIC(5,2),
    gst_amount NUMERIC(15,2),
    line_sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pi_line_invoice ON pi_line(purchase_invoice_id);
CREATE INDEX idx_pi_line_item ON pi_line(item_id);
ALTER TABLE pi_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY pi_line_rls ON pi_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE purchase_return (
    purchase_return_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    purchase_invoice_id UUID REFERENCES purchase_invoice(purchase_invoice_id) ON DELETE SET NULL,
    return_date DATE NOT NULL,
    reason VARCHAR(255),
    status voucher_status DEFAULT 'DRAFT',
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_purchase_return_org_firm ON purchase_return(org_id, firm_id);
CREATE INDEX idx_purchase_return_party ON purchase_return(party_id);
ALTER TABLE purchase_return ENABLE ROW LEVEL SECURITY;
CREATE POLICY purchase_return_rls ON purchase_return USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE pr_line (
    pr_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    purchase_return_id UUID NOT NULL REFERENCES purchase_return(purchase_return_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE SET NULL,
    qty NUMERIC(15,4),
    rate NUMERIC(15,4),
    line_amount NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pr_line_return ON pr_line(purchase_return_id);
CREATE INDEX idx_pr_line_item ON pr_line(item_id);
ALTER TABLE pr_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY pr_line_rls ON pr_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE landed_cost_entry (
    landed_cost_entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    grn_id UUID REFERENCES grn(grn_id) ON DELETE RESTRICT,
    cost_type VARCHAR(50) NOT NULL,
    supplier VARCHAR(255),
    amount NUMERIC(15,2),
    gst_amount NUMERIC(15,2),
    allocation_rule VARCHAR(50),
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_landed_cost_entry_grn ON landed_cost_entry(grn_id);
ALTER TABLE landed_cost_entry ENABLE ROW LEVEL SECURITY;
CREATE POLICY landed_cost_entry_rls ON landed_cost_entry USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 6. MANUFACTURING (Design, BOM, Routing, MO, QC, Labour, Overhead)
-- =============================================================================

CREATE TABLE design (
    design_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_design_firm ON design(firm_id);
ALTER TABLE design ENABLE ROW LEVEL SECURITY;
CREATE POLICY design_rls ON design USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE bom (
    bom_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    design_id UUID NOT NULL REFERENCES design(design_id) ON DELETE RESTRICT,
    finished_item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    version_number SMALLINT DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, finished_item_id, version_number)
);
CREATE INDEX idx_bom_firm_item ON bom(firm_id, finished_item_id);
ALTER TABLE bom ENABLE ROW LEVEL SECURITY;
CREATE POLICY bom_rls ON bom USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE bom_line (
    bom_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    bom_id UUID NOT NULL REFERENCES bom(bom_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty_required NUMERIC(15,4) NOT NULL,
    uom uom_type NOT NULL,
    is_optional BOOLEAN DEFAULT FALSE,
    part_role VARCHAR(50),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_bom_line_bom ON bom_line(bom_id);
CREATE INDEX idx_bom_line_item ON bom_line(item_id);
ALTER TABLE bom_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY bom_line_rls ON bom_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE operation_master (
    operation_master_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    operation_type operation_type,
    default_duration_mins NUMERIC(10,2),
    cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_operation_master_firm ON operation_master(firm_id);
ALTER TABLE operation_master ENABLE ROW LEVEL SECURITY;
CREATE POLICY operation_master_rls ON operation_master USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE routing (
    routing_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    design_id UUID NOT NULL REFERENCES design(design_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    version_number SMALLINT DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code, version_number)
);
CREATE INDEX idx_routing_firm_design ON routing(firm_id, design_id);
ALTER TABLE routing ENABLE ROW LEVEL SECURITY;
CREATE POLICY routing_rls ON routing USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE routing_edge (
    routing_edge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    routing_id UUID NOT NULL REFERENCES routing(routing_id) ON DELETE CASCADE,
    from_operation_id UUID NOT NULL REFERENCES operation_master(operation_master_id) ON DELETE RESTRICT,
    to_operation_id UUID NOT NULL REFERENCES operation_master(operation_master_id) ON DELETE RESTRICT,
    edge_type routing_edge_type DEFAULT 'FINISH_TO_START',
    threshold_qty NUMERIC(15,4),
    threshold_pct NUMERIC(5,2),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_routing_edge_routing ON routing_edge(routing_id);
ALTER TABLE routing_edge ENABLE ROW LEVEL SECURITY;
CREATE POLICY routing_edge_rls ON routing_edge USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE manufacturing_order (
    manufacturing_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    design_id UUID NOT NULL REFERENCES design(design_id) ON DELETE RESTRICT,
    finished_item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    bom_id UUID REFERENCES bom(bom_id) ON DELETE SET NULL,
    routing_id UUID REFERENCES routing(routing_id) ON DELETE SET NULL,
    mo_type mo_type DEFAULT 'BULK',
    status mo_status DEFAULT 'DRAFT',
    mo_date DATE NOT NULL,
    planned_qty NUMERIC(15,4) NOT NULL,
    produced_qty NUMERIC(15,4) DEFAULT 0,
    scrap_qty NUMERIC(15,4) DEFAULT 0,
    by_product_qty NUMERIC(15,4) DEFAULT 0,
    completion_policy VARCHAR(50) DEFAULT 'ALL_OR_NONE',
    cost_pool NUMERIC(15,2) DEFAULT 0,
    cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_mo_org_firm ON manufacturing_order(org_id, firm_id);
CREATE INDEX idx_mo_design ON manufacturing_order(design_id);
CREATE INDEX idx_mo_status ON manufacturing_order(status);
ALTER TABLE manufacturing_order ENABLE ROW LEVEL SECURITY;
CREATE POLICY manufacturing_order_rls ON manufacturing_order USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE mo_material_line (
    mo_material_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    manufacturing_order_id UUID NOT NULL REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty_required NUMERIC(15,4),
    qty_issued NUMERIC(15,4) DEFAULT 0,
    qty_scrap NUMERIC(15,4) DEFAULT 0,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_mo_material_line_mo ON mo_material_line(manufacturing_order_id);
CREATE INDEX idx_mo_material_line_item ON mo_material_line(item_id);
ALTER TABLE mo_material_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY mo_material_line_rls ON mo_material_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE mo_operation (
    mo_operation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    manufacturing_order_id UUID NOT NULL REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE CASCADE,
    operation_master_id UUID NOT NULL REFERENCES operation_master(operation_master_id) ON DELETE RESTRICT,
    operation_sequence SMALLINT,
    qty_in NUMERIC(15,4),
    qty_out NUMERIC(15,4) DEFAULT 0,
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_mo_operation_mo ON mo_operation(manufacturing_order_id);
CREATE INDEX idx_mo_operation_sequence ON mo_operation(manufacturing_order_id, operation_sequence);
ALTER TABLE mo_operation ENABLE ROW LEVEL SECURITY;
CREATE POLICY mo_operation_rls ON mo_operation USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE qc_plan (
    qc_plan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    applies_to_item_id UUID REFERENCES item(item_id) ON DELETE SET NULL,
    applies_to_operation_id UUID REFERENCES operation_master(operation_master_id) ON DELETE SET NULL,
    checkpoints JSONB,
    sampling qc_sampling DEFAULT 'ONE_HUNDRED_PCT',
    aql_level VARCHAR(10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_qc_plan_firm ON qc_plan(firm_id);
ALTER TABLE qc_plan ENABLE ROW LEVEL SECURITY;
CREATE POLICY qc_plan_rls ON qc_plan USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE qc_result (
    qc_result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    manufacturing_order_id UUID REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE SET NULL,
    mo_operation_id UUID REFERENCES mo_operation(mo_operation_id) ON DELETE SET NULL,
    qc_plan_id UUID REFERENCES qc_plan(qc_plan_id) ON DELETE SET NULL,
    unit_id VARCHAR(100),
    checkpoint VARCHAR(100),
    test_value VARCHAR(255),
    specification VARCHAR(255),
    pass_fail qc_status DEFAULT 'PENDING',
    defect_code VARCHAR(50),
    disposition disposition_type,
    inspector_id UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_qc_result_mo ON qc_result(manufacturing_order_id);
CREATE INDEX idx_qc_result_mo_operation ON qc_result(mo_operation_id);
ALTER TABLE qc_result ENABLE ROW LEVEL SECURITY;
CREATE POLICY qc_result_rls ON qc_result USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE labour_slip (
    labour_slip_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    mo_operation_id UUID REFERENCES mo_operation(mo_operation_id) ON DELETE SET NULL,
    employee_id UUID REFERENCES party(party_id) ON DELETE RESTRICT,
    operation_date DATE NOT NULL,
    qty_completed NUMERIC(15,4),
    piece_rate NUMERIC(15,4),
    amount NUMERIC(15,2),
    status VARCHAR(50) DEFAULT 'DRAFT',
    approved_by UUID REFERENCES app_user(user_id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_labour_slip_mo_operation ON labour_slip(mo_operation_id);
CREATE INDEX idx_labour_slip_employee ON labour_slip(employee_id);
ALTER TABLE labour_slip ENABLE ROW LEVEL SECURITY;
CREATE POLICY labour_slip_rls ON labour_slip USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE overhead_rate (
    overhead_rate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    period DATE NOT NULL,
    cost_centre_id UUID NOT NULL REFERENCES cost_centre(cost_centre_id) ON DELETE RESTRICT,
    driver VARCHAR(50),
    rate NUMERIC(15,6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, period, cost_centre_id)
);
CREATE INDEX idx_overhead_rate_firm_period ON overhead_rate(firm_id, period);
ALTER TABLE overhead_rate ENABLE ROW LEVEL SECURITY;
CREATE POLICY overhead_rate_rls ON overhead_rate USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 7. JOB WORK (Job Work Order, Challans, Bill)
-- =============================================================================

CREATE TABLE job_work_order (
    job_work_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    karigar_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    jwo_date DATE NOT NULL,
    expected_return_date DATE,
    status job_work_status DEFAULT 'DRAFT',
    total_amount NUMERIC(15,2),
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_jwo_firm ON job_work_order(firm_id);
CREATE INDEX idx_jwo_karigar ON job_work_order(karigar_id);
ALTER TABLE job_work_order ENABLE ROW LEVEL SECURITY;
CREATE POLICY job_work_order_rls ON job_work_order USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE outward_challan (
    outward_challan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    job_work_order_id UUID REFERENCES job_work_order(job_work_order_id) ON DELETE SET NULL,
    karigar_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    challan_date DATE NOT NULL,
    status challan_status DEFAULT 'DRAFT',
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(255),
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_outward_challan_firm ON outward_challan(firm_id);
CREATE INDEX idx_outward_challan_karigar ON outward_challan(karigar_id);
ALTER TABLE outward_challan ENABLE ROW LEVEL SECURITY;
CREATE POLICY outward_challan_rls ON outward_challan USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE outward_challan_line (
    outward_challan_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    outward_challan_id UUID NOT NULL REFERENCES outward_challan(outward_challan_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE SET NULL,
    mo_ref UUID REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE SET NULL,
    qty NUMERIC(15,4) NOT NULL,
    process_description VARCHAR(255),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_outward_challan_line_challan ON outward_challan_line(outward_challan_id);
ALTER TABLE outward_challan_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY outward_challan_line_rls ON outward_challan_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE inward_challan (
    inward_challan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    outward_challan_id UUID REFERENCES outward_challan(outward_challan_id) ON DELETE SET NULL,
    karigar_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    challan_date DATE NOT NULL,
    received_date DATE,
    status challan_status DEFAULT 'DRAFT',
    total_qty_received NUMERIC(15,4),
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_inward_challan_firm ON inward_challan(firm_id);
CREATE INDEX idx_inward_challan_karigar ON inward_challan(karigar_id);
ALTER TABLE inward_challan ENABLE ROW LEVEL SECURITY;
CREATE POLICY inward_challan_rls ON inward_challan USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE inward_challan_line (
    inward_challan_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    inward_challan_id UUID NOT NULL REFERENCES inward_challan(inward_challan_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty_received NUMERIC(15,4),
    mo_ref UUID REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE SET NULL,
    allocation_pct NUMERIC(5,2),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_inward_challan_line_challan ON inward_challan_line(inward_challan_id);
ALTER TABLE inward_challan_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY inward_challan_line_rls ON inward_challan_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE job_work_bill (
    job_work_bill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    karigar_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    bill_date DATE NOT NULL,
    amount NUMERIC(15,2),
    gst_amount NUMERIC(15,2),
    status voucher_status DEFAULT 'DRAFT',
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_jw_bill_firm ON job_work_bill(firm_id);
CREATE INDEX idx_jw_bill_karigar ON job_work_bill(karigar_id);
ALTER TABLE job_work_bill ENABLE ROW LEVEL SECURITY;
CREATE POLICY job_work_bill_rls ON job_work_bill USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 8. SALES (Quotation, SO, Delivery Challan, SI, Returns, Pick Wave, Credit Profile)
-- =============================================================================

CREATE TABLE quotation (
    quotation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    salesperson_id UUID REFERENCES app_user(user_id) ON DELETE SET NULL,
    quote_date DATE NOT NULL,
    validity_days SMALLINT DEFAULT 30,
    validity_end_date DATE,
    status quote_status DEFAULT 'DRAFT',
    quote_version SMALLINT DEFAULT 1,
    parent_quote_id UUID REFERENCES quotation(quotation_id) ON DELETE SET NULL,
    lost_reason VARCHAR(255),
    total_amount NUMERIC(15,2),
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_quotation_org_firm ON quotation(org_id, firm_id);
CREATE INDEX idx_quotation_party ON quotation(party_id);
CREATE INDEX idx_quotation_status ON quotation(status);
ALTER TABLE quotation ENABLE ROW LEVEL SECURITY;
CREATE POLICY quotation_rls ON quotation USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE quote_line (
    quote_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    quotation_id UUID NOT NULL REFERENCES quotation(quotation_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty NUMERIC(15,4) NOT NULL,
    price NUMERIC(15,4) NOT NULL,
    line_amount NUMERIC(15,2),
    gst_rate NUMERIC(5,2),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_quote_line_quotation ON quote_line(quotation_id);
ALTER TABLE quote_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY quote_line_rls ON quote_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE sales_order (
    sales_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    quotation_id UUID REFERENCES quotation(quotation_id) ON DELETE SET NULL,
    salesperson_id UUID REFERENCES app_user(user_id) ON DELETE SET NULL,
    so_date DATE NOT NULL,
    delivery_date DATE,
    status sales_order_status DEFAULT 'DRAFT',
    total_amount NUMERIC(15,2),
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_so_org_firm ON sales_order(org_id, firm_id);
CREATE INDEX idx_so_party ON sales_order(party_id);
CREATE INDEX idx_so_status ON sales_order(status);
ALTER TABLE sales_order ENABLE ROW LEVEL SECURITY;
CREATE POLICY sales_order_rls ON sales_order USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE so_line (
    so_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    sales_order_id UUID NOT NULL REFERENCES sales_order(sales_order_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty_ordered NUMERIC(15,4) NOT NULL,
    qty_dispatched NUMERIC(15,4) DEFAULT 0,
    price NUMERIC(15,4) NOT NULL,
    line_amount NUMERIC(15,2),
    gst_rate NUMERIC(5,2),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_so_line_so ON so_line(sales_order_id);
CREATE INDEX idx_so_line_item ON so_line(item_id);
ALTER TABLE so_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY so_line_rls ON so_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE delivery_challan (
    delivery_challan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    sales_order_id UUID REFERENCES sales_order(sales_order_id) ON DELETE SET NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    bill_to_address TEXT,
    ship_to_address TEXT,
    place_of_supply_state VARCHAR(2),
    dispatch_date DATE NOT NULL,
    status VARCHAR(50) DEFAULT 'DRAFT',
    total_qty NUMERIC(15,4),
    total_amount NUMERIC(15,2),
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_dc_org_firm ON delivery_challan(org_id, firm_id);
CREATE INDEX idx_dc_party ON delivery_challan(party_id);
CREATE INDEX idx_dc_so ON delivery_challan(sales_order_id);
ALTER TABLE delivery_challan ENABLE ROW LEVEL SECURITY;
CREATE POLICY delivery_challan_rls ON delivery_challan USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE dc_line (
    dc_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    delivery_challan_id UUID NOT NULL REFERENCES delivery_challan(delivery_challan_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE SET NULL,
    qty_dispatched NUMERIC(15,4) NOT NULL,
    price NUMERIC(15,4),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dc_line_dc ON dc_line(delivery_challan_id);
CREATE INDEX idx_dc_line_item ON dc_line(item_id);
ALTER TABLE dc_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY dc_line_rls ON dc_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE sales_invoice (
    sales_invoice_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    delivery_challan_id UUID REFERENCES delivery_challan(delivery_challan_id) ON DELETE SET NULL,
    salesperson_id UUID REFERENCES app_user(user_id) ON DELETE SET NULL,
    invoice_date DATE NOT NULL,
    bill_to_address TEXT,
    ship_to_address TEXT,
    place_of_supply_state VARCHAR(2),
    invoice_type VARCHAR(50),
    invoice_amount NUMERIC(15,2),
    gst_amount NUMERIC(15,2),
    status voucher_status DEFAULT 'DRAFT',
    irn_id UUID,
    eway_bill_id UUID,
    notes TEXT,
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_si_org_firm ON sales_invoice(org_id, firm_id);
CREATE INDEX idx_si_party ON sales_invoice(party_id);
CREATE INDEX idx_si_status ON sales_invoice(status);
ALTER TABLE sales_invoice ENABLE ROW LEVEL SECURITY;
CREATE POLICY sales_invoice_rls ON sales_invoice USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE si_line (
    si_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoice(sales_invoice_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    qty NUMERIC(15,4) NOT NULL,
    price NUMERIC(15,4) NOT NULL,
    line_amount NUMERIC(15,2),
    gst_rate NUMERIC(5,2),
    gst_amount NUMERIC(15,2),
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_si_line_invoice ON si_line(sales_invoice_id);
CREATE INDEX idx_si_line_item ON si_line(item_id);
ALTER TABLE si_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY si_line_rls ON si_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE sales_return (
    sales_return_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE RESTRICT,
    sales_invoice_id UUID REFERENCES sales_invoice(sales_invoice_id) ON DELETE SET NULL,
    return_date DATE NOT NULL,
    reason VARCHAR(255),
    status voucher_status DEFAULT 'DRAFT',
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_sr_org_firm ON sales_return(org_id, firm_id);
CREATE INDEX idx_sr_party ON sales_return(party_id);
ALTER TABLE sales_return ENABLE ROW LEVEL SECURITY;
CREATE POLICY sales_return_rls ON sales_return USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE sr_line (
    sr_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    sales_return_id UUID NOT NULL REFERENCES sales_return(sales_return_id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES item(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES lot(lot_id) ON DELETE SET NULL,
    qty NUMERIC(15,4),
    price NUMERIC(15,4),
    line_amount NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sr_line_return ON sr_line(sales_return_id);
ALTER TABLE sr_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY sr_line_rls ON sr_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE pick_wave (
    pick_wave_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    dispatch_date DATE NOT NULL,
    status VARCHAR(50) DEFAULT 'DRAFT',
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pick_wave_firm ON pick_wave(firm_id);
CREATE INDEX idx_pick_wave_status ON pick_wave(status);
ALTER TABLE pick_wave ENABLE ROW LEVEL SECURITY;
CREATE POLICY pick_wave_rls ON pick_wave USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE pick_wave_line (
    pick_wave_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    pick_wave_id UUID NOT NULL REFERENCES pick_wave(pick_wave_id) ON DELETE CASCADE,
    delivery_challan_id UUID REFERENCES delivery_challan(delivery_challan_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pick_wave_line_wave ON pick_wave_line(pick_wave_id);
ALTER TABLE pick_wave_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY pick_wave_line_rls ON pick_wave_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE customer_credit_profile (
    customer_credit_profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    party_id UUID NOT NULL REFERENCES party(party_id) ON DELETE CASCADE,
    credit_limit NUMERIC(15,2),
    credit_days SMALLINT,
    used_credit NUMERIC(15,2) DEFAULT 0,
    available_credit NUMERIC(15,2),
    last_review_date DATE,
    reviewed_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, party_id)
);
CREATE INDEX idx_customer_credit_firm_party ON customer_credit_profile(firm_id, party_id);
ALTER TABLE customer_credit_profile ENABLE ROW LEVEL SECURITY;
CREATE POLICY customer_credit_profile_rls ON customer_credit_profile USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 9. ACCOUNTING (Voucher, Journal Lines, Bank, Cheque, FX, Loans)
-- =============================================================================

CREATE TABLE voucher (
    voucher_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    voucher_type voucher_type NOT NULL,
    series VARCHAR(50) NOT NULL,
    number VARCHAR(50) NOT NULL,
    voucher_date DATE NOT NULL,
    reference_type VARCHAR(50),
    reference_id UUID,
    narration TEXT,
    status voucher_status DEFAULT 'DRAFT',
    cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    total_debit NUMERIC(15,2),
    total_credit NUMERIC(15,2),
    created_by UUID REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    prev_hash BYTEA,
    this_hash BYTEA,
    UNIQUE (org_id, firm_id, series, number)
);
CREATE INDEX idx_voucher_org_firm ON voucher(org_id, firm_id);
CREATE INDEX idx_voucher_type ON voucher(voucher_type);
CREATE INDEX idx_voucher_status ON voucher(status);
CREATE INDEX idx_voucher_date ON voucher(voucher_date);
ALTER TABLE voucher ENABLE ROW LEVEL SECURITY;
CREATE POLICY voucher_rls ON voucher USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE voucher_line (
    voucher_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    voucher_id UUID NOT NULL REFERENCES voucher(voucher_id) ON DELETE CASCADE,
    ledger_id UUID NOT NULL REFERENCES ledger(ledger_id) ON DELETE RESTRICT,
    line_type journal_line_type NOT NULL,
    amount NUMERIC(15,2) NOT NULL,
    cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    description TEXT,
    sequence SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_voucher_line_voucher ON voucher_line(voucher_id);
CREATE INDEX idx_voucher_line_ledger ON voucher_line(ledger_id);
ALTER TABLE voucher_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY voucher_line_rls ON voucher_line USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE bank_account (
    bank_account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    ledger_id UUID NOT NULL REFERENCES ledger(ledger_id) ON DELETE RESTRICT,
    bank_name VARCHAR(255),
    account_number BYTEA,
    ifsc_code VARCHAR(11),
    account_type VARCHAR(50),
    balance NUMERIC(15,2),
    last_reconciled_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_bank_account_firm ON bank_account(firm_id);
CREATE INDEX idx_bank_account_ledger ON bank_account(ledger_id);
ALTER TABLE bank_account ENABLE ROW LEVEL SECURITY;
CREATE POLICY bank_account_rls ON bank_account USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE cheque (
    cheque_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    bank_account_id UUID NOT NULL REFERENCES bank_account(bank_account_id) ON DELETE RESTRICT,
    cheque_number VARCHAR(20) NOT NULL,
    cheque_date DATE NOT NULL,
    payee_name VARCHAR(255),
    amount NUMERIC(15,2),
    status cheque_status DEFAULT 'ISSUED',
    clearing_date DATE,
    bounce_reason VARCHAR(255),
    voucher_id UUID REFERENCES voucher(voucher_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, bank_account_id, cheque_number)
);
CREATE INDEX idx_cheque_firm_bank ON cheque(firm_id, bank_account_id);
CREATE INDEX idx_cheque_status ON cheque(status);
ALTER TABLE cheque ENABLE ROW LEVEL SECURITY;
CREATE POLICY cheque_rls ON cheque USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE fixed_asset (
    fixed_asset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    acquisition_date DATE,
    acquisition_cost NUMERIC(15,2),
    cost_ledger_id UUID REFERENCES ledger(ledger_id) ON DELETE SET NULL,
    depreciation_ledger_id UUID REFERENCES ledger(ledger_id) ON DELETE SET NULL,
    depreciation_method VARCHAR(50),
    useful_life_years SMALLINT,
    residual_value NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_fixed_asset_firm ON fixed_asset(firm_id);
ALTER TABLE fixed_asset ENABLE ROW LEVEL SECURITY;
CREATE POLICY fixed_asset_rls ON fixed_asset USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE loan (
    loan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    loan_type VARCHAR(50),
    lender VARCHAR(255),
    principal_amount NUMERIC(15,2),
    interest_rate NUMERIC(5,2),
    disbursement_date DATE,
    maturity_date DATE,
    emi_amount NUMERIC(15,2),
    emi_frequency VARCHAR(50),
    has_moratorium BOOLEAN DEFAULT FALSE,
    moratorium_end_date DATE,
    loan_ledger_id UUID REFERENCES ledger(ledger_id) ON DELETE SET NULL,
    interest_ledger_id UUID REFERENCES ledger(ledger_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_loan_firm ON loan(firm_id);
ALTER TABLE loan ENABLE ROW LEVEL SECURITY;
CREATE POLICY loan_rls ON loan USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE electronic_credit_ledger (
    electronic_credit_ledger_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    period_date DATE,
    opening_balance NUMERIC(15,2),
    itc_accrued NUMERIC(15,2),
    itc_utilized NUMERIC(15,2),
    closing_balance NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, period_date)
);
CREATE INDEX idx_electronic_credit_ledger_firm ON electronic_credit_ledger(firm_id);
ALTER TABLE electronic_credit_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY electronic_credit_ledger_rls ON electronic_credit_ledger USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE electronic_cash_ledger (
    electronic_cash_ledger_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    period_date DATE,
    opening_balance NUMERIC(15,2),
    challan_deposits NUMERIC(15,2),
    utilized NUMERIC(15,2),
    closing_balance NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, period_date)
);
CREATE INDEX idx_electronic_cash_ledger_firm ON electronic_cash_ledger(firm_id);
ALTER TABLE electronic_cash_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY electronic_cash_ledger_rls ON electronic_cash_ledger USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE inter_firm_relationship (
    inter_firm_relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_a_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE CASCADE,
    firm_b_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE CASCADE,
    relationship_type inter_firm_relationship_type,
    default_pricing_policy VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, firm_a_id, firm_b_id)
);
CREATE INDEX idx_inter_firm_relationship_org ON inter_firm_relationship(org_id);
ALTER TABLE inter_firm_relationship ENABLE ROW LEVEL SECURITY;
CREATE POLICY inter_firm_relationship_rls ON inter_firm_relationship USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 10. COMPLIANCE (E-Way Bill, IRN, GST Returns, ITC-04, TDS)
-- =============================================================================

CREATE TABLE eway_bill (
    eway_bill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    reference_type VARCHAR(50),
    reference_id UUID,
    eway_bill_number VARCHAR(12),
    eway_bill_date DATE,
    validity_date DATE,
    status eway_status DEFAULT 'DRAFT',
    transporter_id VARCHAR(100),
    vehicle_number VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_eway_bill_firm ON eway_bill(firm_id);
CREATE INDEX idx_eway_bill_reference ON eway_bill(reference_type, reference_id);
CREATE INDEX idx_eway_bill_status ON eway_bill(status);
ALTER TABLE eway_bill ENABLE ROW LEVEL SECURITY;
CREATE POLICY eway_bill_rls ON eway_bill USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE irn (
    irn_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    sales_invoice_id UUID REFERENCES sales_invoice(sales_invoice_id) ON DELETE SET NULL,
    irn_number VARCHAR(64),
    ack_number VARCHAR(64),
    irn_date TIMESTAMP,
    qr_code_url TEXT,
    status irn_status DEFAULT 'DRAFT',
    signed_invoice BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_irn_firm ON irn(firm_id);
CREATE INDEX idx_irn_sales_invoice ON irn(sales_invoice_id);
CREATE INDEX idx_irn_status ON irn(status);
ALTER TABLE irn ENABLE ROW LEVEL SECURITY;
CREATE POLICY irn_rls ON irn USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE gstr_filing (
    gstr_filing_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    gstr_type VARCHAR(10),
    period_month SMALLINT,
    period_year SMALLINT,
    filing_date DATE,
    status VARCHAR(50),
    acknowledgment_number VARCHAR(100),
    data_snapshot JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, gstr_type, period_month, period_year)
);
CREATE INDEX idx_gstr_filing_firm_period ON gstr_filing(firm_id, period_month, period_year);
ALTER TABLE gstr_filing ENABLE ROW LEVEL SECURITY;
CREATE POLICY gstr_filing_rls ON gstr_filing USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE itc04_entry (
    itc04_entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    filing_period_month SMALLINT,
    filing_period_year SMALLINT,
    is_quarterly BOOLEAN,
    filing_date DATE,
    data_snapshot JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_itc04_entry_firm_period ON itc04_entry(firm_id, filing_period_month, filing_period_year);
ALTER TABLE itc04_entry ENABLE ROW LEVEL SECURITY;
CREATE POLICY itc04_entry_rls ON itc04_entry USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE tds_entry (
    tds_entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    reference_type VARCHAR(50),
    reference_id UUID,
    party_id UUID REFERENCES party(party_id) ON DELETE SET NULL,
    payment_date DATE,
    tds_section VARCHAR(10),
    tds_amount NUMERIC(15,2),
    pan BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_tds_entry_firm ON tds_entry(firm_id);
CREATE INDEX idx_tds_entry_party ON tds_entry(party_id);
ALTER TABLE tds_entry ENABLE ROW LEVEL SECURITY;
CREATE POLICY tds_entry_rls ON tds_entry USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 11. PLATFORM (Outbound Message, Scheduled Report, Feature Flag, Notification, Plan, Subscription)
-- =============================================================================

CREATE TABLE outbound_message (
    outbound_message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    message_type VARCHAR(50),
    recipient VARCHAR(255) NOT NULL,
    subject TEXT,
    body TEXT,
    reference_type VARCHAR(50),
    reference_id UUID,
    status outbound_message_status DEFAULT 'DRAFT',
    attempts SMALLINT DEFAULT 0,
    last_error TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_outbound_message_org ON outbound_message(org_id);
CREATE INDEX idx_outbound_message_status ON outbound_message(status);
CREATE INDEX idx_outbound_message_created ON outbound_message(created_at DESC);
ALTER TABLE outbound_message ENABLE ROW LEVEL SECURITY;
CREATE POLICY outbound_message_rls ON outbound_message USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE scheduled_report (
    scheduled_report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    firm_id UUID REFERENCES firm(firm_id) ON DELETE RESTRICT,
    report_type VARCHAR(100),
    recipient_email VARCHAR(255),
    schedule_cron VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES app_user(user_id)
);
CREATE INDEX idx_scheduled_report_org ON scheduled_report(org_id);
ALTER TABLE scheduled_report ENABLE ROW LEVEL SECURITY;
CREATE POLICY scheduled_report_rls ON scheduled_report USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE feature_flag (
    feature_flag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    feature_key VARCHAR(100) NOT NULL UNIQUE,
    feature_name VARCHAR(255),
    description TEXT,
    status feature_flag_status DEFAULT 'OFF',
    rollout_percentage SMALLINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_feature_flag_org ON feature_flag(org_id);
ALTER TABLE feature_flag ENABLE ROW LEVEL SECURITY;
CREATE POLICY feature_flag_rls ON feature_flag USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE notification (
    notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(org_id) ON DELETE RESTRICT,
    user_id UUID REFERENCES app_user(user_id) ON DELETE CASCADE,
    notification_type notification_type,
    title VARCHAR(255),
    message TEXT,
    reference_type VARCHAR(50),
    reference_id UUID,
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_notification_user ON notification(user_id);
CREATE INDEX idx_notification_is_read ON notification(is_read);
ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
CREATE POLICY notification_rls ON notification USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE plan (
    plan_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_type plan_type NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_monthly NUMERIC(15,2),
    price_yearly NUMERIC(15,2),
    max_users SMALLINT,
    max_firms SMALLINT,
    features JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE subscription (
    subscription_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL UNIQUE REFERENCES organization(org_id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES plan(plan_id) ON DELETE RESTRICT,
    status subscription_status DEFAULT 'TRIAL',
    start_date DATE,
    end_date DATE,
    billing_period VARCHAR(50),
    auto_renew BOOLEAN DEFAULT TRUE,
    current_bill_amount NUMERIC(15,2),
    last_payment_date DATE,
    next_payment_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_subscription_org ON subscription(org_id);
CREATE INDEX idx_subscription_status ON subscription(status);
ALTER TABLE subscription ENABLE ROW LEVEL SECURITY;
CREATE POLICY subscription_rls ON subscription USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- 12. HELPERS (Expense Category, Budget, Commission Scheme)
-- =============================================================================

CREATE TABLE expense_category (
    expense_category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    ledger_id UUID REFERENCES ledger(ledger_id) ON DELETE SET NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, code)
);
CREATE INDEX idx_expense_category_firm ON expense_category(firm_id);
ALTER TABLE expense_category ENABLE ROW LEVEL SECURITY;
CREATE POLICY expense_category_rls ON expense_category USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE budget (
    budget_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    fy_year SMALLINT NOT NULL,
    cost_centre_id UUID REFERENCES cost_centre(cost_centre_id) ON DELETE RESTRICT,
    ledger_id UUID REFERENCES ledger(ledger_id) ON DELETE RESTRICT,
    month SMALLINT,
    budget_amount NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Postgres disallows expressions inside an inline UNIQUE constraint; convert to
-- a UNIQUE INDEX so NULL cost_centre_id is treated as the no-cost-centre sentinel.
CREATE UNIQUE INDEX uq_budget_firm_fy_cc_ledger_month
    ON budget(
        firm_id, fy_year,
        COALESCE(cost_centre_id, '00000000-0000-0000-0000-000000000000'::uuid),
        ledger_id, month
    );
CREATE INDEX idx_budget_firm_fy ON budget(firm_id, fy_year);
ALTER TABLE budget ENABLE ROW LEVEL SECURITY;
CREATE POLICY budget_rls ON budget USING (org_id = current_setting('app.current_org_id')::uuid);

CREATE TABLE commission_scheme (
    commission_scheme_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    firm_id UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    salesperson_id UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    basis VARCHAR(50),
    rate_tiers JSONB,
    incentives JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, salesperson_id)
);
CREATE INDEX idx_commission_scheme_firm_salesperson ON commission_scheme(firm_id, salesperson_id);
ALTER TABLE commission_scheme ENABLE ROW LEVEL SECURITY;
CREATE POLICY commission_scheme_rls ON commission_scheme USING (org_id = current_setting('app.current_org_id')::uuid);

-- =============================================================================
-- PATCH 1 — Phase-1 forward-compatibility hooks
-- Adds: document_series (gapless numbering), invoice_share (send/print history),
--       production_event (event-sourced manufacturing), plus column extensions
--       on sales_invoice and mo_operation so Phase-3 slots in without migration.
-- Companion specs: invoice-lifecycle.md §16, manufacturing-pipeline.md §5.2
-- =============================================================================

-- --- Enums for richer state machines (extend existing voucher_status) -----------
CREATE TYPE invoice_lifecycle_status AS ENUM (
    'DRAFT', 'CONFIRMED', 'FINALIZED', 'POSTED',
    'PARTIALLY_PAID', 'PAID', 'OVERDUE',
    'CANCELLED', 'DISCARDED'
);

CREATE TYPE purchase_invoice_status AS ENUM (
    'DRAFT', 'CONFIRMED', 'MATCHING', 'ON_HOLD', 'DISPUTED',
    'POSTED', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'CANCELLED'
);

CREATE TYPE mo_operation_state AS ENUM (
    'PENDING', 'READY', 'DISPATCHED', 'ACKNOWLEDGED',
    'IN_PROGRESS', 'RECEIVED_PARTIAL', 'RECEIVED_FULL',
    'QC_PENDING', 'REWORK', 'CLOSED', 'SKIPPED', 'CANCELLED'
);

CREATE TYPE stock_stage AS ENUM (
    'RAW', 'CUT',
    'AT_DYEING', 'AT_PRINTING', 'AT_EMBROIDERY', 'AT_HANDWORK',
    'AT_STITCHING', 'AT_WASHING', 'AT_FINISHING',
    'DYED', 'EMBROIDERED', 'HANDWORKED', 'STITCHED', 'WASHED',
    'QC_PENDING', 'FINISHED', 'PACKED',
    'REWORK_QUEUE', 'SECONDS', 'REJECTED', 'SCRAP',
    'DISPATCHED', 'IN_TRANSIT'
);

CREATE TYPE invoice_share_channel AS ENUM (
    'WHATSAPP', 'EMAIL', 'SMS', 'PRINT', 'DOWNLOAD', 'RESEND'
);

CREATE TYPE invoice_share_status AS ENUM (
    'QUEUED', 'SENT', 'DELIVERED', 'READ', 'FAILED'
);

-- --- Document series (gapless numbering per firm × doc_type × FY) ---------------
-- Allocated via SELECT ... FOR UPDATE on invoice finalize / voucher post.
-- Cancelled numbers are retained (not reused). FY roll-over creates new row.
CREATE TABLE document_series (
    series_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL,
    firm_id       UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    doc_type      VARCHAR(50) NOT NULL,       -- 'TAX_INVOICE', 'BILL_OF_SUPPLY', 'CREDIT_NOTE', 'DEBIT_NOTE', 'RCM_SELF', 'DC', 'PO', etc.
    prefix        VARCHAR(20) NOT NULL,       -- 'TI', 'BOS', 'CN', 'RCM', 'DC', ...
    fy            VARCHAR(7) NOT NULL,        -- '25-26'
    last_seq      BIGINT NOT NULL DEFAULT 0,
    padding       SMALLINT NOT NULL DEFAULT 6,  -- zero-pad width
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    UUID REFERENCES app_user(user_id),
    UNIQUE (firm_id, doc_type, fy)
);
CREATE INDEX idx_document_series_lookup ON document_series(firm_id, doc_type, fy) WHERE is_active;
ALTER TABLE document_series ENABLE ROW LEVEL SECURITY;
CREATE POLICY document_series_rls ON document_series
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- --- Invoice share / send history (print, WhatsApp, SMS, email) -----------------
-- One row per send attempt; supports audit "did we remind them?" + delivery SLA.
CREATE TABLE invoice_share (
    share_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL,
    firm_id          UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoice(sales_invoice_id) ON DELETE CASCADE,
    channel          invoice_share_channel NOT NULL,
    recipient        TEXT,                     -- phone, email, or NULL for print/download
    sent_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           invoice_share_status NOT NULL DEFAULT 'QUEUED',
    delivery_receipt JSONB,                    -- Meta/Twilio webhook payload
    error_message    TEXT,
    sent_by          UUID REFERENCES app_user(user_id),
    retry_count      SMALLINT NOT NULL DEFAULT 0,
    idempotency_key  VARCHAR(100)
);
CREATE INDEX idx_invoice_share_invoice ON invoice_share(sales_invoice_id, sent_at DESC);
CREATE INDEX idx_invoice_share_status ON invoice_share(status) WHERE status IN ('QUEUED', 'FAILED');
CREATE UNIQUE INDEX idx_invoice_share_idem ON invoice_share(idempotency_key) WHERE idempotency_key IS NOT NULL;
ALTER TABLE invoice_share ENABLE ROW LEVEL SECURITY;
CREATE POLICY invoice_share_rls ON invoice_share
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- --- Production event log (event-sourced manufacturing) -------------------------
-- Every state transition on MO / operation / stock emits an event here.
-- Idempotent via idempotency_key; supports replay, projections, audit.
-- PARTITION BY RANGE (created_at) monthly when volume warrants.
CREATE TABLE production_event (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    firm_id         UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    manufacturing_order_id UUID REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE RESTRICT,
    mo_operation_id UUID REFERENCES mo_operation(mo_operation_id) ON DELETE RESTRICT,
    event_type      VARCHAR(60) NOT NULL,
    -- event_type examples:
    --   mo.created, mo.released, mo.started, mo.partially_completed, mo.completed, mo.closed, mo.cancelled
    --   operation.ready, operation.dispatched, operation.acknowledged, operation.started,
    --   operation.progressed, operation.received, operation.qc_recorded, operation.closed,
    --   operation.rework_created, operation.skipped, operation.cancelled
    --   labour.logged, overhead.applied, stock.moved
    payload         JSONB NOT NULL,
    actor_user_id   UUID REFERENCES app_user(user_id),
    actor_party_id  UUID REFERENCES party(party_id),  -- e.g. karigar via WhatsApp webhook
    actor_source    VARCHAR(40),                      -- 'WEB', 'ANDROID', 'WHATSAPP_WEBHOOK', 'SYSTEM'
    idempotency_key VARCHAR(100),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- business timestamp (can be backdated for offline-sync)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- server receipt timestamp
    prev_event_hash BYTEA,                              -- chain to prior event of same org for tamper-evidence
    event_hash      BYTEA
);
CREATE INDEX idx_prod_event_mo ON production_event(manufacturing_order_id, occurred_at);
CREATE INDEX idx_prod_event_mo_op ON production_event(mo_operation_id, occurred_at);
CREATE INDEX idx_prod_event_type_time ON production_event(firm_id, event_type, occurred_at DESC);
CREATE UNIQUE INDEX idx_prod_event_idem ON production_event(org_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
-- PARTITION BY RANGE (created_at) — see ops playbook; implement when org's daily event volume > 10k.
ALTER TABLE production_event ENABLE ROW LEVEL SECURITY;
CREATE POLICY production_event_rls ON production_event
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- --- sales_invoice extensions (lifecycle + MO link + cost centre + GST hooks) ---
ALTER TABLE sales_invoice
    ADD COLUMN IF NOT EXISTS lifecycle_status invoice_lifecycle_status NOT NULL DEFAULT 'DRAFT',
    ADD COLUMN IF NOT EXISTS finalized_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS paid_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS due_date        DATE,
    ADD COLUMN IF NOT EXISTS irn_status      VARCHAR(20),      -- NULL | PENDING | GENERATED | CANCELLED | FAILED
    ADD COLUMN IF NOT EXISTS irn_hash        VARCHAR(128),
    ADD COLUMN IF NOT EXISTS eway_status     VARCHAR(20),      -- NULL | PENDING | GENERATED | CANCELLED | EXPIRED
    ADD COLUMN IF NOT EXISTS revises_invoice_id UUID REFERENCES sales_invoice(sales_invoice_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS linked_mo_id    UUID REFERENCES manufacturing_order(manufacturing_order_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS cost_centre_id  UUID REFERENCES cost_centre(cost_centre_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS tax_type        VARCHAR(20),      -- IGST | CGST_SGST | NIL_LUT | NIL_NOT_A_SUPPLY
    ADD COLUMN IF NOT EXISTS round_off       NUMERIC(6,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS dispatched_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_si_lifecycle_status ON sales_invoice(firm_id, lifecycle_status)
    WHERE lifecycle_status IN ('POSTED','PARTIALLY_PAID','OVERDUE');
CREATE INDEX IF NOT EXISTS idx_si_due_date ON sales_invoice(firm_id, due_date)
    WHERE lifecycle_status IN ('POSTED','PARTIALLY_PAID','OVERDUE');
CREATE INDEX IF NOT EXISTS idx_si_linked_mo ON sales_invoice(linked_mo_id) WHERE linked_mo_id IS NOT NULL;

-- --- purchase_invoice extensions (3-way-match state) ----------------------------
ALTER TABLE purchase_invoice
    ADD COLUMN IF NOT EXISTS lifecycle_status purchase_invoice_status NOT NULL DEFAULT 'DRAFT',
    ADD COLUMN IF NOT EXISTS match_result    JSONB,          -- {lines:[{pi_line_id, po_variance_pct, grn_variance_pct, decision}]}
    ADD COLUMN IF NOT EXISTS paid_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS due_date        DATE,
    ADD COLUMN IF NOT EXISTS held_by         UUID REFERENCES app_user(user_id),
    ADD COLUMN IF NOT EXISTS hold_reason     TEXT;

-- --- mo_operation state machine + karigar + event-sourcing hooks ----------------
-- Rewrite status from free-text VARCHAR to enum; carry firm_id for RLS consistency.
ALTER TABLE mo_operation
    ADD COLUMN IF NOT EXISTS firm_id         UUID REFERENCES firm(firm_id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS state           mo_operation_state NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS karigar_party_id UUID REFERENCES party(party_id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS executor        VARCHAR(20) NOT NULL DEFAULT 'IN_HOUSE',  -- IN_HOUSE | JOB_WORK
    ADD COLUMN IF NOT EXISTS outward_challan_id UUID REFERENCES outward_challan(outward_challan_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS inward_challan_id  UUID REFERENCES inward_challan(inward_challan_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS qty_rejected    NUMERIC(15,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS qty_wastage     NUMERIC(15,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS qty_byproduct   NUMERIC(15,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_accrued    NUMERIC(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rework_of_mo_operation_id UUID REFERENCES mo_operation(mo_operation_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS is_rework_paid  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS expected_return_date DATE,
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS version         INT NOT NULL DEFAULT 0;     -- optimistic locking for state transitions

CREATE INDEX IF NOT EXISTS idx_mo_op_state ON mo_operation(firm_id, state)
    WHERE state IN ('READY','DISPATCHED','IN_PROGRESS','RECEIVED_PARTIAL','QC_PENDING');
CREATE INDEX IF NOT EXISTS idx_mo_op_karigar ON mo_operation(karigar_party_id) WHERE karigar_party_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mo_op_expected_return ON mo_operation(expected_return_date)
    WHERE state IN ('DISPATCHED','ACKNOWLEDGED','IN_PROGRESS');

-- --- stock_ledger: stage column (typed) ----------------------------------------
-- Existing stock_ledger likely has a free-text status/stage column; if it's varchar,
-- we add a typed stage column alongside and keep the varchar for legacy writes
-- until a migration sweeps.
ALTER TABLE stock_ledger
    ADD COLUMN IF NOT EXISTS from_stage stock_stage,
    ADD COLUMN IF NOT EXISTS to_stage   stock_stage,
    ADD COLUMN IF NOT EXISTS mo_operation_id UUID REFERENCES mo_operation(mo_operation_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_stock_ledger_mo_op ON stock_ledger(mo_operation_id) WHERE mo_operation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stock_ledger_to_stage ON stock_ledger(firm_id, to_stage) WHERE to_stage IS NOT NULL;

-- --- Payment allocation (ties receipt/payment voucher lines to invoices) --------
-- Supports FIFO auto-allocation + user-directed allocation + TDS split per §6.
CREATE TABLE payment_allocation (
    allocation_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL,
    firm_id          UUID NOT NULL REFERENCES firm(firm_id) ON DELETE RESTRICT,
    voucher_id       UUID NOT NULL REFERENCES voucher(voucher_id) ON DELETE CASCADE,
    -- Exactly one of these is non-null per row:
    sales_invoice_id UUID REFERENCES sales_invoice(sales_invoice_id) ON DELETE RESTRICT,
    purchase_invoice_id UUID REFERENCES purchase_invoice(purchase_invoice_id) ON DELETE RESTRICT,
    amount           NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    tds_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
    allocated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    allocated_by     UUID REFERENCES app_user(user_id),
    allocation_mode  VARCHAR(20) NOT NULL DEFAULT 'AUTO',   -- AUTO | MANUAL
    reversed_by_allocation_id UUID REFERENCES payment_allocation(allocation_id) ON DELETE SET NULL,
    CONSTRAINT chk_payment_alloc_target CHECK (
        (sales_invoice_id IS NOT NULL)::int +
        (purchase_invoice_id IS NOT NULL)::int = 1
    )
);
CREATE INDEX idx_pay_alloc_voucher ON payment_allocation(voucher_id);
CREATE INDEX idx_pay_alloc_si ON payment_allocation(sales_invoice_id) WHERE sales_invoice_id IS NOT NULL;
CREATE INDEX idx_pay_alloc_pi ON payment_allocation(purchase_invoice_id) WHERE purchase_invoice_id IS NOT NULL;
ALTER TABLE payment_allocation ENABLE ROW LEVEL SECURITY;
CREATE POLICY payment_allocation_rls ON payment_allocation
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- --- Idempotency tracking for mutating API calls (offline-sync safety) ----------
-- Referenced by specs: manufacturing-pipeline.md §5, invoice-lifecycle.md §5,
-- architecture.md §17.8.2. Retains request/response fingerprint for 14d.
CREATE TABLE api_idempotency (
    idempotency_key  VARCHAR(100) NOT NULL,
    org_id           UUID NOT NULL,
    user_id          UUID REFERENCES app_user(user_id) ON DELETE SET NULL,
    endpoint         VARCHAR(200) NOT NULL,
    request_hash     BYTEA NOT NULL,
    response_status  SMALLINT,
    response_body    JSONB,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '14 days'),
    PRIMARY KEY (idempotency_key, org_id)
);
CREATE INDEX idx_api_idempotency_expires ON api_idempotency(expires_at);
ALTER TABLE api_idempotency ENABLE ROW LEVEL SECURITY;
CREATE POLICY api_idempotency_rls ON api_idempotency
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- --- Migration notes ------------------------------------------------------------
-- Ordering in Alembic migration: (1) new enums, (2) new tables, (3) ALTER columns,
-- (4) indexes, (5) RLS policies. All forward-only; no data loss.
-- Back-fill plan for sales_invoice.lifecycle_status: map existing status values
-- (DRAFT->DRAFT, POSTED->POSTED, RECONCILED->PAID, VOIDED->CANCELLED).
-- Back-fill for mo_operation.state: map existing status VARCHAR into enum via
-- UPDATE + CASE; then DROP old status column in a later migration (never drop in
-- the same release that adds the replacement).

-- =============================================================================
-- PATCH 2 — Review fixes (P1 sweep)
-- Addresses review.md items:
--   P1-1  Audit columns on every tenant-scoped table
--   P1-3  mo_operation.firm_id NOT NULL + scoped RLS (flagged, migration path)
--   P1-4  uom / hsn scope decision
--   P1-6  payment_allocation CHECK via num_nonnulls
--   P1-8  inter_firm_relationship.default_pricing_policy
--   P1-9  Manufacturing tables annotated (Phase-3 scope)
-- =============================================================================

-- --- P1-1: Audit-columns sweep (idempotent; PL/pgSQL DO block) --------------------
-- Every tenant-scoped table gets: updated_at, created_by, updated_by, deleted_at.
-- created_at is already universal. Global catalog tables (uom, hsn, permission, plan)
-- and pure-link tables (role_permission, user_role) are explicitly exempt.
DO $audit_sweep$
DECLARE
    r RECORD;
    exempt_tables TEXT[] := ARRAY[
        'uom', 'hsn', 'permission', 'plan',                         -- global catalogs
        'role_permission', 'user_role', 'item_uom_alt',             -- pure join tables
        'api_idempotency', 'audit_log', 'production_event',          -- append-only / system
        'stock_ledger', 'voucher_line',                              -- append-only ledgers
        'alembic_version'                                            -- alembic internals (no org_id)
    ];
    has_col BOOLEAN;
BEGIN
    FOR r IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
          AND table_name <> ALL(exempt_tables)
    LOOP
        -- updated_at
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=r.table_name AND column_name='updated_at'
        ) INTO has_col;
        IF NOT has_col THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()',
                r.table_name);
        END IF;

        -- created_by
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=r.table_name AND column_name='created_by'
        ) INTO has_col;
        IF NOT has_col THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN created_by UUID',
                r.table_name);
        END IF;

        -- updated_by
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=r.table_name AND column_name='updated_by'
        ) INTO has_col;
        IF NOT has_col THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN updated_by UUID',
                r.table_name);
        END IF;

        -- deleted_at (soft-delete)
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=r.table_name AND column_name='deleted_at'
        ) INTO has_col;
        IF NOT has_col THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN deleted_at TIMESTAMPTZ',
                r.table_name);
            -- partial index: soft-delete queries filter WHERE deleted_at IS NULL
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS idx_%I_not_deleted ON %I (org_id) WHERE deleted_at IS NULL',
                r.table_name, r.table_name);
        END IF;
    END LOOP;
END
$audit_sweep$;

-- Soft-delete convention (application layer):
--   * Application queries append  `AND deleted_at IS NULL`  via a SQLAlchemy base-class filter.
--   * GST-retained entities cannot be hard-deleted until retention lapses (statute-bound).
--   * A nightly job purges rows with deleted_at > retention_cutoff for non-regulated tables.

-- Standard trigger for updated_at (apply per-table as needed; minimal overhead).
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- Apply the trigger in a follow-up migration per-table to avoid bloat here.
-- Alternative: set updated_at explicitly in the service layer (preferred for auditability).

-- --- P1-3: mo_operation.firm_id — migration path ---------------------------------
-- PATCH 1 added firm_id nullable. Data backfill happens at app release:
--   UPDATE mo_operation o SET firm_id = mo.firm_id
--   FROM manufacturing_order mo WHERE o.manufacturing_order_id = mo.manufacturing_order_id;
-- Then tighten:
--   ALTER TABLE mo_operation ALTER COLUMN firm_id SET NOT NULL;
--   DROP POLICY mo_operation_rls ON mo_operation;
--   CREATE POLICY mo_operation_rls ON mo_operation USING (
--     org_id  = current_setting('app.current_org_id')::uuid
--     AND (firm_id = current_setting('app.current_firm_id', true)::uuid
--          OR current_setting('app.current_firm_id', true) = '')
--   );
-- Run in a deploy with the backfill SQL above, then DDL tightening in the next release.
-- (Never tighten NOT NULL and backfill in the same migration — creates a failed-startup risk.)

-- --- P1-4: uom / hsn scope — declared global read-only catalog -------------------
-- These are shared across all tenants. RLS is intentionally OFF; writes are restricted
-- via role grants (the `app_user_role` role has SELECT only). Maintenance inserts are
-- done via a dedicated `catalog_admin` role used by system-seeded data.
-- Revoke write to the application role:
REVOKE INSERT, UPDATE, DELETE ON uom FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON hsn FROM PUBLIC;
-- (Application connects as `app_user_role`; those REVOKEs take effect there.)
-- If per-firm custom UOMs / HSNs are needed later, we add `firm_uom_override` and
-- `firm_hsn_override` tenant-scoped tables rather than mutating the catalog.

-- --- P1-6: payment_allocation CHECK upgraded to num_nonnulls ---------------------
ALTER TABLE payment_allocation DROP CONSTRAINT IF EXISTS chk_payment_alloc_target;
ALTER TABLE payment_allocation
    ADD CONSTRAINT chk_payment_alloc_one_target
    CHECK (num_nonnulls(sales_invoice_id, purchase_invoice_id) = 1);
-- Rationale: num_nonnulls is self-documenting Postgres-native (9.6+). The earlier
-- cast-to-int-and-sum trick was clever but obscure; a maintainer would not recognize
-- the invariant at a glance.

-- --- P1-8: inter_firm_relationship gets default_pricing_policy -------------------
ALTER TABLE inter_firm_relationship
    ADD COLUMN IF NOT EXISTS default_pricing_policy VARCHAR(30) NOT NULL DEFAULT 'LANDED_COST',
    ADD COLUMN IF NOT EXISTS transfer_price_markup_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
    ADD CONSTRAINT chk_inter_firm_pricing_policy CHECK (
        default_pricing_policy IN ('LANDED_COST', 'COST_PLUS_MARKUP', 'CUSTOM', 'STANDARD_COST')
    );
-- LANDED_COST: transfer at stock's current landed cost (default)
-- COST_PLUS_MARKUP: landed_cost * (1 + transfer_price_markup_pct/100)
-- CUSTOM: user specifies per-transfer rate at the time of invoice creation
-- STANDARD_COST: uses item-level standard cost (if maintained)

-- --- P1-9: Manufacturing tables — Phase-3 scope marker --------------------------
-- The following tables ship in Phase 1 (schema only) but are NOT activated via UI
-- or API until Phase 3. They can safely remain empty with zero functional impact:
--   design, bom, bom_line, routing, routing_edge, operation_master,
--   manufacturing_order, mo_material_line, mo_operation, qc_plan, qc_result,
--   labour_slip, overhead_rate, production_event.
-- Keeping them in Phase-1 DDL avoids a breaking migration when Phase 3 lands.
-- Enforced via feature flag: `feature_flag.key = 'mfg.enabled'` defaults FALSE.

-- --- P1 summary ------------------------------------------------------------------
-- After applying PATCH 1 + PATCH 2:
--   * All tenant-scoped tables have updated_at, created_by, updated_by, deleted_at.
--   * Soft-delete filter index exists on all non-exempt tables.
--   * Set-updated-at trigger function available (apply per-table as desired).
--   * mo_operation.firm_id migration path documented.
--   * uom/hsn declared global, writes role-restricted.
--   * payment_allocation invariant is now self-documenting.
--   * inter_firm_relationship supports four pricing policies.
--   * Manufacturing tables flagged Phase-3 (scaffold-only).

-- End of DDL (P0-1 fixed · PATCH 1 · PATCH 2 · Phase-1 forward-compatible)
