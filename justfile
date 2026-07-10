# Git for Windows ships sh.exe at this standard path; on macOS/Linux the default sh is used
set windows-shell := ["C:/Program Files/Git/bin/sh.exe", "-cu"]
set positional-arguments

# List available recipes
default:
    @just --list

# Split expenses from one or more CSVs (bare names resolve in payment-csvs/)
split +csvs:
    @uv run split_money/split-finances.py "$@"
