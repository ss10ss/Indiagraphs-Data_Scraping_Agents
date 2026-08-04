# RBI Automation Generator

Generates a `.py` scraper + `.yml` GitHub Actions workflow from a single
config file, following the established pattern (retry logic, dedupe against
`data_points` then `data_points_draft`, screenshot steps, English comments).

## Usage

```
python generate_automation.py my_config.json
```

This writes `<file_name>.py` and `<file_name>.yml` in the current directory.

## Config fields

| Field | Required | Notes |
|---|---|---|
| `dataset_id` | yes | Supabase numeric dataset id |
| `workflow_name` | yes | e.g. `067_total-digital-payments-volume-monthly` |
| `file_name` | yes | Used for both output filenames and the `python <file_name>.py` line in the yml |
| `search_text` | yes | What to type into the RBI search box |
| `dropdown_filter` | yes | Text to match in the search-mode dropdown, e.g. `"all of the words"` or `"one or more words"` |
| `report_link_text` | yes | Text (or partial text) of the report link to click |
| `requires_new_format_tab` | yes | `true`/`false` - whether to click the "New Format" tab after the iframe loads |
| `extraction_mode` | yes | One of `"simple"`, `"idref_suffix"`, `"fiscal_year"` (see below) |
| `month_bid` | yes | `bid` attribute of the Month/Year column cells |
| `value_bid` | yes | `bid` attribute of the target value column cells |
| `value_idref_prefix` | only for `idref_suffix` | e.g. `"2.Dz.1I"` - the row-suffix number gets appended automatically |
| `fy_header_bid` | only for `fiscal_year` | `bid` of the fiscal-year header row |
| `value_c` | only for `fiscal_year` | `c` attribute distinguishing the target sub-column |
| `conversion` | yes | One of `"none"`, `"decimal_shift_left_1"` (Lakh→Million), `"round_int"` |
| `period_type` | no (default `MONTH`) | Stored in Supabase `period_type` |
| `rows_to_scrape` | no (default `5`) | How many recent rows to check/insert per run |
| `cron` | no (default `'30 3 15-25 * *'`) | GitHub Actions cron schedule |
| `cron_comment` | no | Comment shown next to the cron line in the yml |
| `check_table` / `draft_table` | no (defaults `data_points` / `data_points_draft`) | |
| `created_by` | no (has a default UUID) | Only override if a different Supabase user id is needed |

## Extraction modes

- **`simple`** — month and value are plain `<td><span>` cells in the same
  `<tr>`, matched by row position. (Pattern used by `112_usd-inr-monthly`.)
- **`idref_suffix`** — month and value cells are matched by a shared numeric
  suffix in their `idref` attribute, with a fallback to read the value from
  an `aria-label` when that row happens to be the currently
  "selected/highlighted" cell on the site. (Pattern used by
  `067_total-digital-payments-volume-monthly`.)
- **`fiscal_year`** — table has fiscal-year header rows above the monthly
  rows; the fiscal year is tracked and combined with the month name to work
  out the correct calendar year (Jan/Feb/Mar roll into the second half of
  the fiscal year). (Pattern used by `111_silver-price-monthly`.)

## Example

`example_config_067.json` reproduces the
`067_total-digital-payments-volume-monthly` automation — use it as a
starting template and adjust the fields for the new report.

## What's NOT covered

Sites/reports with quirks beyond these three patterns (e.g. pagination,
multi-step forms, a different alert flow) will still need a manual tweak
after generating — the generator gets you the full boilerplate + the
correct pattern, not a guarantee that every RBI report behaves identically.
