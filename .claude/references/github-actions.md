# GitHub Actions for PromptBench

Sources: astral-sh/setup-uv README (checked 2026-10-19 via Context7) and GitHub Actions docs. Pin third-party actions to a commit SHA. Update the pins deliberately.

## `promptbench.yml` — PR gate

```yaml
name: promptbench
on:
  pull_request:
    paths: ["prompts/**", "goldens/**", "rubrics/**", "src/**", "promptbench.toml", "uv.lock"]
  workflow_dispatch:

concurrency:
  group: promptbench-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write          # sticky PR comment

jobs:
  gate:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      SENTENCE_TRANSFORMERS_HOME: ${{ github.workspace }}/.cache/st
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0
        with:
          enable-cache: true
      - uses: actions/cache@v4
        with:
          path: .cache/st
          key: st-all-MiniLM-L6-v2
      - run: uv sync --frozen
      - run: uv run promptbench validate

      - name: Detect secrets
        id: secrets
        run: echo "has_keys=${{ secrets.ANTHROPIC_API_KEY != '' }}" >> "$GITHUB_OUTPUT"

      - name: Run gate
        if: steps.secrets.outputs.has_keys == 'true'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          CI_RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: uv run promptbench run --report-md report.md --junit junit.xml --json results.json

      - name: Fork PR notice
        if: steps.secrets.outputs.has_keys != 'true'
        run: echo "Secrets unavailable (fork PR) — ran \`validate\` only." >> "$GITHUB_STEP_SUMMARY"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: promptbench-report
          path: |
            report.md
            junit.xml
            results.json
          if-no-files-found: ignore
```

Notes:
- `secrets` can't be used directly in `if:`, which is why a step output is used.
- `promptbench run` writes the Markdown report to `$GITHUB_STEP_SUMMARY` itself when that variable is set (SPEC §12). There's no need to `cat` it in.
- The job's exit code is the PromptBench exit code: 1 = regression, 3 = infra. Don't add `continue-on-error`. Use the tool's warn-only mode during rollout instead.
- `uv run --frozen` / `uv sync --frozen` fail if `uv.lock` is stale. That's intended.

## Sticky PR comment

Update one comment per PR instead of adding a new one each run. Find an existing comment by a hidden marker (`<!-- promptbench-report -->` at the top of `report.md`) and edit it, otherwise create one:

```yaml
      - name: Comment on PR
        if: always() && github.event_name == 'pull_request' && hashFiles('report.md') != ''
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          id=$(gh api "repos/${{ github.repository }}/issues/${{ github.event.pull_request.number }}/comments" \
               --jq '.[] | select(.body | startswith("<!-- promptbench-report -->")) | .id' | head -1)
          if [ -n "$id" ]; then
            gh api -X PATCH "repos/${{ github.repository }}/issues/comments/$id" -F body=@report.md
          else
            gh pr comment ${{ github.event.pull_request.number }} --body-file report.md
          fi
```

## `baseline-update.yml` — accept a new quality level

```yaml
name: baseline-update
on:
  workflow_dispatch:
    inputs:
      suites:  {description: "Comma-separated suites (empty = all)", required: false}
      reason:  {description: "Why the new level is acceptable", required: true}

permissions:
  contents: write
  pull-requests: write

jobs:
  update:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: baseline-approval      # required reviewers configured in repo settings
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0
        with: {enable-cache: true}
      - run: uv sync --frozen
      - env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
        run: |
          args=""; for s in $(echo "${{ inputs.suites }}" | tr ',' ' '); do args="$args --suite $s"; done
          uv run promptbench run $args --json results.json || [ $? -eq 1 ]   # 1 is expected; 2/3 abort
          uv run promptbench baseline update $args --from-results results.json
      - env: {GH_TOKEN: "${{ github.token }}"}
        run: |
          branch="baseline-update/${{ github.run_id }}"
          git switch -c "$branch"
          git add baselines/
          git -c user.name="promptbench-bot" -c user.email="promptbench-bot@users.noreply.github.com" \
              commit -m "Update baselines: ${{ inputs.reason }}"
          git push -u origin "$branch"
          gh pr create --title "Update baselines" --body "${{ inputs.reason }}"
```

## Secrets

| Secret | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | judge |
| `LANGSMITH_API_KEY` | tracking (optional; missing → tracking off with warning) |

Never `echo` a secret or pass one on a command line. Pass secrets through `env:`. PRs from forks receive no secrets. Never switch to `pull_request_target` to work around this, because that runs untrusted PR code with secrets.

## Nightly live tests

A separate scheduled workflow runs `uv run pytest -m live` with `PROMPTBENCH_LIVE=1`. Keep it out of PR runs.
