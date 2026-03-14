-- PostgreSQL initialization script
-- Creates schemas for service isolation

CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS market_data;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS advisor;
CREATE SCHEMA IF NOT EXISTS tax;
CREATE SCHEMA IF NOT EXISTS sync_svc;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
