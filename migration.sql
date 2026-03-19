BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> f8c18ac43ed7

CREATE TABLE categories (
    id SERIAL NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    description TEXT, 
    parent_id INTEGER, 
    sort_order INTEGER NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(parent_id) REFERENCES categories (id) ON DELETE CASCADE, 
    CONSTRAINT uq_category_code_parent UNIQUE (code, parent_id)
);

CREATE TABLE employee_types (
    id SERIAL NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    description TEXT, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (code), 
    UNIQUE (name)
);

CREATE TABLE evaluation_types (
    id SERIAL NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    description TEXT, 
    is_active BOOLEAN NOT NULL, 
    config JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (code), 
    UNIQUE (name)
);

CREATE TABLE organizations (
    id SERIAL NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    address VARCHAR(500), 
    phone VARCHAR(50), 
    is_active BOOLEAN NOT NULL, 
    meta JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    UNIQUE (code)
);

CREATE TABLE criteria (
    id SERIAL NOT NULL, 
    category_id INTEGER, 
    evaluation_type_id INTEGER NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    code VARCHAR(100) NOT NULL, 
    description TEXT, 
    sort_order INTEGER NOT NULL, 
    is_required BOOLEAN NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE CASCADE, 
    FOREIGN KEY(evaluation_type_id) REFERENCES evaluation_types (id) ON DELETE CASCADE
);

CREATE TABLE employees (
    id SERIAL NOT NULL, 
    telegram_id BIGINT, 
    employee_type_id INTEGER NOT NULL, 
    organization_id INTEGER NOT NULL, 
    full_name VARCHAR(255) NOT NULL, 
    username VARCHAR(255), 
    phone VARCHAR(50), 
    position VARCHAR(100), 
    hire_date DATE, 
    is_active BOOLEAN NOT NULL, 
    meta JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(employee_type_id) REFERENCES employee_types (id) ON DELETE RESTRICT, 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT, 
    UNIQUE (telegram_id)
);

CREATE TABLE evaluations (
    id SERIAL NOT NULL, 
    evaluation_type_id INTEGER NOT NULL, 
    organization_id INTEGER NOT NULL, 
    filled_by_employee_id INTEGER NOT NULL, 
    evaluated_employee_id INTEGER, 
    evaluation_date TIMESTAMP WITH TIME ZONE DEFAULT 'NOW()' NOT NULL, 
    total_criteria INTEGER NOT NULL, 
    passed_criteria INTEGER NOT NULL, 
    failed_criteria INTEGER NOT NULL, 
    score_percentage FLOAT NOT NULL, 
    comment TEXT, 
    status VARCHAR(20) NOT NULL, 
    meta JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT check_different_employees CHECK (evaluated_employee_id IS NULL OR filled_by_employee_id != evaluated_employee_id), 
    FOREIGN KEY(evaluated_employee_id) REFERENCES employees (id) ON DELETE RESTRICT, 
    FOREIGN KEY(evaluation_type_id) REFERENCES evaluation_types (id) ON DELETE RESTRICT, 
    FOREIGN KEY(filled_by_employee_id) REFERENCES employees (id) ON DELETE RESTRICT, 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT
);

CREATE TABLE criterion_values (
    id SERIAL NOT NULL, 
    evaluation_id INTEGER NOT NULL, 
    criterion_id INTEGER NOT NULL, 
    value BOOLEAN NOT NULL, 
    notes TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(criterion_id) REFERENCES criteria (id) ON DELETE CASCADE, 
    FOREIGN KEY(evaluation_id) REFERENCES evaluations (id) ON DELETE CASCADE, 
    CONSTRAINT uq_evaluation_criterion UNIQUE (evaluation_id, criterion_id)
);

INSERT INTO alembic_version (version_num) VALUES ('f8c18ac43ed7') RETURNING alembic_version.version_num;

-- Running upgrade f8c18ac43ed7 -> f09e7daacbbe

CREATE TABLE users (
    id SERIAL NOT NULL, 
    telegram_id BIGINT NOT NULL, 
    username VARCHAR(255), 
    first_name VARCHAR(255), 
    last_name VARCHAR(255), 
    chat_id BIGINT NOT NULL, 
    is_verified BOOLEAN NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_user_telegram_chat UNIQUE (telegram_id, chat_id)
);

UPDATE alembic_version SET version_num='f09e7daacbbe' WHERE alembic_version.version_num = 'f8c18ac43ed7';

-- Running upgrade f09e7daacbbe -> f12565b39847

ALTER TABLE users ADD COLUMN version INTEGER NOT NULL;

UPDATE alembic_version SET version_num='f12565b39847' WHERE alembic_version.version_num = 'f09e7daacbbe';

-- Running upgrade f12565b39847 -> 3bf4ec2474c3

INSERT INTO employee_types (name, code, description, is_active) VALUES 
            ('���������', 'employee', '������� ��������� �����������', true),
            ('������������', 'manager', '������������ ������������� ��� ������', true),
            ('�������������', 'administrator', '������������� �������', true)
            ON CONFLICT (code) DO NOTHING;

UPDATE alembic_version SET version_num='3bf4ec2474c3' WHERE alembic_version.version_num = 'f12565b39847';

-- Running upgrade 3bf4ec2474c3 -> e0977be82069

ALTER TABLE employees DROP CONSTRAINT employees_telegram_id_key;

ALTER TABLE employees ADD CONSTRAINT uq_employee_telegram_organization UNIQUE (telegram_id, organization_id);

UPDATE alembic_version SET version_num='e0977be82069' WHERE alembic_version.version_num = '3bf4ec2474c3';

-- Running upgrade e0977be82069 -> f5447bfcdd5f

ALTER TABLE criteria ADD COLUMN organization_id INTEGER NOT NULL;

ALTER TABLE criteria ADD FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE;

UPDATE alembic_version SET version_num='f5447bfcdd5f' WHERE alembic_version.version_num = 'e0977be82069';

-- Running upgrade f5447bfcdd5f -> remove_eval_type_criteria

ALTER TABLE criteria DROP CONSTRAINT criteria_evaluation_type_id_fkey;

ALTER TABLE criteria DROP COLUMN evaluation_type_id;

UPDATE alembic_version SET version_num='remove_eval_type_criteria' WHERE alembic_version.version_num = 'f5447bfcdd5f';

-- Running upgrade remove_eval_type_criteria -> add_org_to_eval_types

ALTER TABLE evaluation_types ADD COLUMN organization_id INTEGER;

ALTER TABLE evaluation_types DROP CONSTRAINT evaluation_types_name_key;

ALTER TABLE evaluation_types DROP CONSTRAINT evaluation_types_code_key;

ALTER TABLE evaluation_types ADD CONSTRAINT fk_evaluation_types_organization_id FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE;

ALTER TABLE evaluation_types ADD CONSTRAINT uq_evaluation_types_org_name UNIQUE (organization_id, name);

ALTER TABLE evaluation_types ADD CONSTRAINT uq_evaluation_types_org_code UNIQUE (organization_id, code);

CREATE INDEX ix_evaluation_types_organization_id ON evaluation_types (organization_id);

UPDATE alembic_version SET version_num='add_org_to_eval_types' WHERE alembic_version.version_num = 'remove_eval_type_criteria';

-- Running upgrade f5447bfcdd5f -> add_criterion_sets

CREATE TABLE criterion_sets (
    id SERIAL NOT NULL, 
    organization_id INTEGER NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    description TEXT, 
    is_default BOOLEAN DEFAULT 'false' NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    CONSTRAINT uq_organization_criterion_set_name UNIQUE (organization_id, name)
);

CREATE TABLE criterion_set_criterion (
    criterion_set_id INTEGER NOT NULL, 
    criterion_id INTEGER NOT NULL, 
    PRIMARY KEY (criterion_set_id, criterion_id), 
    FOREIGN KEY(criterion_set_id) REFERENCES criterion_sets (id) ON DELETE CASCADE, 
    FOREIGN KEY(criterion_id) REFERENCES criteria (id) ON DELETE CASCADE
);

INSERT INTO alembic_version (version_num) VALUES ('add_criterion_sets') RETURNING alembic_version.version_num;

-- Running upgrade add_criterion_sets -> 277eb272246b

ALTER TABLE evaluations ADD COLUMN criterion_set_id INTEGER;

ALTER TABLE evaluations ADD CONSTRAINT fk_evaluations_criterion_set_id FOREIGN KEY(criterion_set_id) REFERENCES criterion_sets (id) ON DELETE SET NULL;

UPDATE alembic_version SET version_num='277eb272246b' WHERE alembic_version.version_num = 'add_criterion_sets';

-- Running upgrade 277eb272246b -> add_is_bot_admin

ALTER TABLE users ADD COLUMN is_bot_administrator BOOLEAN DEFAULT 'false' NOT NULL;

UPDATE alembic_version SET version_num='add_is_bot_admin' WHERE alembic_version.version_num = '277eb272246b';

-- Running upgrade 277eb272246b -> add_criterion_value_types

ALTER TABLE criteria ADD COLUMN value_type VARCHAR(20) DEFAULT 'boolean' NOT NULL;

ALTER TABLE criterion_values ALTER COLUMN value DROP NOT NULL;

ALTER TABLE criterion_values ADD COLUMN value_json JSONB;

UPDATE criterion_values
        SET value_json = jsonb_build_object('type', 'boolean', 'value', value::text)
        WHERE value_json IS NULL AND value IS NOT NULL;

UPDATE criterion_values
        SET value_json = jsonb_build_object('type', 'boolean', 'value', 'false')
        WHERE value_json IS NULL;

ALTER TABLE criterion_values ALTER COLUMN value_json SET NOT NULL;

ALTER TABLE criterion_values ALTER COLUMN value_json SET DEFAULT '{"type": "boolean", "value": false}';

INSERT INTO alembic_version (version_num) VALUES ('add_criterion_value_types') RETURNING alembic_version.version_num;

COMMIT;

-- Add current_organization_id to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS current_organization_id INTEGER;

