#!/usr/bin/env bash

#Idea:
#https://gist.github.com/plembo/409a8d7b1bae66622dbcd26337bbb185

set -euo pipefail

ATTACHMENTSDIR="_resources"

print_usage() {
    echo "Usage: $0 filename.docx"
    echo "Converts filename.docx to filename.md using pandoc and"
    echo "extracts media to ./$ATTACHMENTSDIR/"
}

# Check that exactly one argument is provided
if [ "$#" -ne 1 ]; then
    echo "Error: missing or too many arguments."
    print_usage
    exit 1
fi

input_file="$1"

# Check that the argument ends with .docx
case "$input_file" in
    *.docx) ;;
    *)
        echo "Error: input file must have .docx extension."
        print_usage
        exit 1
        ;;
esac

# Check that the file exists
if [ ! -f "$input_file" ]; then
    echo "Error: file '$input_file' not found."
    exit 1
fi

# Strip .docx to get base name
myfilename="${input_file%.docx}"

# (Optional) ensure attachments dir root exists
mkdir -p "./$ATTACHMENTSDIR"

# Run pandoc conversion
export myfilename
pandoc -t markdown_strict \
    --extract-media="./$ATTACHMENTSDIR" \
    "$myfilename.docx" \
    -o "$myfilename.md"

echo "Converted '$input_file' -> '$myfilename.md'"
echo "Media extracted to './$ATTACHMENTSDIR'"
