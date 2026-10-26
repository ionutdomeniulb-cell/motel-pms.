-- PostgreSQL production-oriented schema for Popas Căprioara PMS
-- Requires PostgreSQL 14+ and the btree_gist extension.
-- Run this against a NEW database after reviewing it with your developer.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS room_types (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    max_guests SMALLINT NOT NULL CHECK (max_guests > 0),
    description TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS rooms (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_number TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    room_type_id BIGINT NOT NULL REFERENCES room_types(id),
    floor_label TEXT NOT NULL DEFAULT '',
    max_guests SMALLINT NOT NULL CHECK (max_guests > 0),
    amenities JSONB NOT NULL DEFAULT '{}'::jsonb,
    operational_status TEXT NOT NULL DEFAULT 'active'
      CHECK (operational_status IN ('active', 'maintenance', 'out_of_service')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS guests (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS channels (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    channel_kind TEXT NOT NULL CHECK (channel_kind IN ('direct', 'ota', 'agency', 'other')),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO channels (code, name, channel_kind) VALUES
 ('DIRECT', 'Rezervare directă', 'direct'),
 ('PHONE', 'Telefon', 'direct'),
 ('WHATSAPP', 'WhatsApp', 'direct'),
 ('WEBSITE', 'Website propriu', 'direct'),
 ('BOOKING_COM', 'Booking.com', 'ota'),
 ('EXPEDIA', 'Expedia', 'ota'),
 ('AGENCY', 'Agenție', 'agency'),
 ('OTHER', 'Altă sursă', 'other')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS bookings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    booking_code TEXT NOT NULL UNIQUE,
    guest_id BIGINT NOT NULL REFERENCES guests(id),
    room_id BIGINT NOT NULL REFERENCES rooms(id),
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    adults SMALLINT NOT NULL DEFAULT 1 CHECK (adults >= 1),
    children SMALLINT NOT NULL DEFAULT 0 CHECK (children >= 0),
    status TEXT NOT NULL DEFAULT 'confirmed'
      CHECK (status IN ('provisional', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'no_show')),
    channel_id BIGINT NOT NULL REFERENCES channels(id),
    currency CHAR(3) NOT NULL DEFAULT 'RON',
    nightly_rate NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (nightly_rate >= 0),
    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    deposit_amount NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (deposit_amount >= 0),
    notes TEXT NOT NULL DEFAULT '',
    external_reservation_id TEXT,
    created_by BIGINT,
    updated_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (check_out > check_in),
    EXCLUDE USING gist (
      room_id WITH =,
      daterange(check_in, check_out, '[)') WITH &&
    ) WHERE (status <> 'cancelled')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_channel_external_id
  ON bookings(channel_id, external_reservation_id)
  WHERE external_reservation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bookings_dates ON bookings(check_in, check_out);
CREATE INDEX IF NOT EXISTS idx_bookings_room_dates ON bookings(room_id, check_in, check_out);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);

CREATE TABLE IF NOT EXISTS room_blocks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES rooms(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date > start_date),
    EXCLUDE USING gist (
      room_id WITH =,
      daterange(start_date, end_date, '[)') WITH &&
    ) WHERE (status = 'active')
);

-- Channel inventory mapping for a future Booking.com / channel-manager connection.
-- A channel room type can map to a set of physical rooms of the same PMS room type.
CREATE TABLE IF NOT EXISTS channel_room_type_mappings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel_id BIGINT NOT NULL REFERENCES channels(id),
    room_type_id BIGINT NOT NULL REFERENCES room_types(id),
    external_room_type_id TEXT NOT NULL,
    external_room_type_name TEXT NOT NULL DEFAULT '',
    external_rate_plan_id TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (channel_id, external_room_type_id, external_rate_plan_id)
);

CREATE TABLE IF NOT EXISTS channel_sync_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel_id BIGINT NOT NULL REFERENCES channels(id),
    event_type TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'retry', 'failed', 'ignored')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id BIGINT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before_data JSONB,
    after_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Illustrative starter room types only. Adjust to the real motel inventory.
INSERT INTO room_types (code, name, max_guests) VALUES
 ('DOUBLE', 'Dublă matrimonială', 2),
 ('TWIN', 'Dublă twin', 2),
 ('TRIPLE', 'Triplă', 3),
 ('FAMILY', 'Familială', 4)
ON CONFLICT (code) DO NOTHING;

-- Intentionally do NOT insert 25 rooms: exact room numbers, names, capacities
-- and types must be confirmed with the property before the inventory is activated.
