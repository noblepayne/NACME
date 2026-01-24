#!/usr/bin/env bash

set -euo pipefail

# TODO: needs rg, sed

# Script to recursively find and replace two values in files using ripgrep
# Usage: ./script.sh <search_term> <replace_term> [directory]

if [ $# -lt 2 ]; then
	echo "Usage: $0 <search_term> <replace_term> [directory]"
	echo "Example: $0 'oldValue' 'newValue' ."
	exit 1
fi

SEARCH="$1"
REPLACE="$2"
DIR="${3:-.}"

# Verify ripgrep is installed
if ! command -v rg &>/dev/null; then
	echo "Error: ripgrep (rg) is not installed. Please install it first."
	exit 1
fi

echo "Searching for '$SEARCH' in $DIR..."

# Helper function to escape strings for sed
escape_for_sed() {
	printf '%s\n' "$1" | sed -e 's/[\/&]/\\&/g'
}

SEARCH_ESCAPED=$(escape_for_sed "$SEARCH")
REPLACE_ESCAPED=$(escape_for_sed "$REPLACE")

# Use ripgrep to find all files containing the search term
# -l: list files only, automatically skips binary files
# --fixed-strings: treat pattern as literal string, not regex
rg --no-ignore -l --fixed-strings -- "$SEARCH" "$DIR" | while read -r file; do
	echo "Processing: $file"

	# Use sed with escaped delimiters for safe in-place replacement
	if sed -i "s/$SEARCH_ESCAPED/$REPLACE_ESCAPED/g" "$file"; then
		echo "  ✓ Successfully updated"
	else
		echo "  ✗ Error processing $file"
		exit 1
	fi
done

echo "Done! All occurrences of '$SEARCH' have been replaced with '$REPLACE'"
