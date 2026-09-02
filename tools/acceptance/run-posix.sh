#!/usr/bin/env sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "usage: run-posix.sh <python> <poly> <fixture-dir> <output-dir>" >&2
  exit 2
fi

python_exe=$1
poly_exe=$2
fixture_dir=$3
output_dir=$4
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

"$python_exe" "$script_dir/run_acceptance.py" \
  --poly "$poly_exe" \
  --fixture "$fixture_dir" \
  --output "$output_dir" \
  --platform posix
