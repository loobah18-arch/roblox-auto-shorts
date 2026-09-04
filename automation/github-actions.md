# Realistic GitHub Actions Setup

This is what a **helpful** GitHub Actions workflow looks like for this playbook. It does **not** automate the full pipeline — it automates the *glue* (reminders, linting, prompt prep).

## Workflow: `.github/workflows/weekly-review.yml`

```yaml
name: Weekly Review Reminder

on:
  schedule:
    # Runs every Monday 9:00 AM UTC — adjust to your day
    - cron: '0 9 * * 1'
  workflow_dispatch:  # manual trigger

jobs:
  remind-and-prep:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Prepare Weekly Review input
        run: |
          python3 scripts/weekly_review_prep.py tracker/tracker.csv --output weekly_review_input.txt

      - name: Upload Weekly Review prompt as artifact
        uses: actions/upload-artifact@v4
        with:
          name: weekly-review-prompt
          path: weekly_review_input.txt

      - name: Lint tracker CSV
        run: |
          python3 -c "
import csv, sys
required = ['date','campaign','source_timecode','hook_style','value_layer','platform','views','approval','cap_notes','next_test']
with open('tracker/tracker.csv') as f:
    reader = csv.DictReader(f)
    if reader.fieldnames != required:
        print(f'ERROR: columns mismatch. Got {reader.fieldnames}')
        sys.exit(1)
    for i, row in enumerate(reader, 2):
        if not row['date'] or not row['campaign']:
            print(f'Row {i}: missing required date/campaign')
            sys.exit(1)
  print('Tracker OK')
          "

      - name: Create weekly reminder issue
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const title = `📊 Weekly Review — ${new Date().toISOString().split('T')[0]}`;
            const body = `## Weekly Review Reminder
            
            1. Download the **weekly-review-prompt** artifact from this run.
            2. Paste its contents into claude.ai (use the Weekly Review prompt).
            3. Apply the 5 single-variable tests to next week's clips.
            4. Update \`tracker/tracker.csv\` with new data.
            
            **Don't claim causation from small samples.**`;
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title,
              body,
              labels: ['weekly-review']
            });
```

## Workflow: `.github/workflows/lint-campaign-sheet.yml`

```yaml
name: Lint Campaign Sheet

on:
  push:
    paths:
      - 'campaign/**/RULES.md'
  pull_request:
    paths:
      - 'campaign/**/RULES.md'

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate RULES.md structure
        run: |
          for f in campaign/*/RULES.md; do
            echo "Checking $f"
            # Check required fields exist
            for field in "rate" "budget_remaining" "min_payout" "max_per_post" "platforms" "min_length" "max_length" "required_hashtags" "watermark" "prohibited_themes"; do
              if ! grep -qi "$field" "$f"; then
                echo "  ⚠️  Missing: $field"
              fi
            done
          done
```

## Workflow: `.github/workflows/clip-finder-prep.yml`

```yaml
name: Prepare Clip Finder Prompt

on:
  workflow_dispatch:
    inputs:
      campaign:
        description: 'Campaign folder name (e.g., higgsfield-ai)'
        required: true
        type: string
      transcript:
        description: 'Transcript filename in transcript/ folder'
        required: true
        type: string

jobs:
  prep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Prepare Clip Finder input
        run: |
          python3 scripts/prepare_transcript.py \
            "transcript/${{ github.event.inputs.transcript }}" \
            --campaign "${{ github.event.inputs.campaign }}" \
            --output clip_finder_input.txt
      - name: Upload Clip Finder prompt
        uses: actions/upload-artifact@v4
        with:
          name: clip-finder-prompt
          path: clip_finder_input.txt
```

## How to Use This

1. Push this repo to GitHub.
2. Enable Actions.
3. **Weekly:** The `weekly-review.yml` runs Monday, creates an issue, and uploads the prompt artifact — you download, paste to Claude, do the review.
4. **Per campaign:** Go to Actions → "Prepare Clip Finder Prompt" → Run workflow → enter campaign name + transcript file → downloads a ready-to-paste prompt.
5. **On push:** Campaign sheets are linted for required fields.

## What This Does NOT Do

- ❌ Fetch campaigns from Whop (no API)
- ❌ Download assets (no API)
- ❌ Run Clip Finder automatically (you paste to Claude)
- ❌ Verify clips visually (human required)
- ❌ Edit clips (creative human work)
- ❌ Post to platforms (APIs restricted/gated)
- ❌ Submit to Whop (no API)

## Local-First Alternative

You don't need GitHub Actions at all. Just run the scripts locally:

```bash
# Prep Clip Finder for a campaign
python3 scripts/prepare_transcript.py transcript/my_transcript.txt --campaign "higgsfield-ai"

# Prep Weekly Review
python3 scripts/weekly_review_prep.py tracker/tracker.csv
```

Then paste outputs to claude.ai. The repo is a **toolkit**, not a pipeline.