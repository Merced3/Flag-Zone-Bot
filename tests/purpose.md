# Tests Folder Purpose

This folder contains automated tests for the Flag-Zone-Bot project.  
We use **pytest** to ensure critical components work correctly as the system evolves.

## Structure

- **storage_unit_tests/**
  - `conftest.py` → Shared pytest fixtures (common setup/teardown).
  - `test_parquet_writer.py` → Tests for appending candles/objects into Parquet.
  - `test_viewport.py` → Tests for loading viewport slices from Parquet.
  - `test_compaction.py` → Tests that daily and monthly compaction correctly merges part files into a single file, verifies integrity, and deletes redundant parts.

- **purpose.md** → This file. Explains why tests exist and what they cover.

## Why we test

- Catch regressions early (especially storage performance & schema consistency).
- Prove that our storage layer works independently of the live bot.
- Verify that compaction safely funnels millions of small files into clean daily/monthly archives.
- Make the repo more professional (CI/CD and résumé value).
