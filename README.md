# perkolator

A calendar feed that says when American Express Platinum Card (U.S.
personal) benefits need attention, so statement credits do not expire
unnoticed.

Unofficial. Not affiliated with American Express. Benefit terms change;
check them in your own account before relying on anything here.

## Subscribe

```
https://r6e.github.io/perkolator/amex-platinum.ics
```

Add it to any calendar app that can subscribe to an `.ics` address
(usually "add calendar from URL"), then give that calendar a default
notification for all-day events. Subscribed calendars only get
calendar-wide notifications, so that default is what reminds you.

## What you get

| Event | When | Contents |
|---|---|---|
| Monthly sweep | First Saturday | Add all Amex Offers, check upcoming travel, credits closing that month; in January, an enrollment audit |
| Credits closing | 10th of March, June, September, December | Every credit whose period ends that month, split into "needs a purchase or booking" and "automatic, verify the credit posted" |
| Benefit changed | Two days after a change is detected | What American Express added or re-termed, or stopped listing |

Sixteen scheduled events a year. Every benefit is listed, with no
personalisation: skip the lines that do not apply to you.

Each sweep ends with the date the terms were last verified. If that date
is more than six weeks before the event, the watcher has stopped.

## How it works

- `data/benefits.yaml` is the source of truth: amount, cadence, kind and
  action for each benefit. `data/changes.yaml` records detected changes.
- `perkolator build` validates both and writes the feed. The feed is not
  kept in git: `.github/workflows/publish.yml` builds it from `main` and
  deploys it to GitHub Pages on every push, weekly, and after each
  watcher run.
- `.github/workflows/watch.yml` runs monthly, in four jobs with
  separate permissions and no shared cache:
  1. **page** has a read-only token and no credential. It downloads the
     issuer's page (`scripts/fetch-source.sh`) and reduces it to text
     (`perkolator extract-text`).
  2. **watch** runs a model on that text with `watcher/PROMPT.md`
     (`scripts/run-watcher.sh`). The model has two file tools and
     nothing else: no shell, no network, and it can edit only the two
     data files. The files are screened
     (`scripts/screen-data-files.sh`) and uploaded; they are the job's
     only output. This is the only job that can reach the model
     credential, so it installs nothing but the pinned model tool.
  3. **commit** runs no model. `scripts/apply-watcher-data.sh` takes
     exactly those two files. The job validates them, refuses an update
     that drops a benefit or its schedule, rewrites them from the
     validated content (`perkolator normalize`) so that comments and
     anything else the schema does not hold are dropped, runs the tests
     and commits them to `main`.
  4. **publish** tests, rebuilds and deploys the feed.

To change the data by hand, edit it on `main` like any other file, then
run `uv run perkolator normalize`. That rewrites both files in the one
form CI accepts (`perkolator normalize --check`); comments do not survive
it. The change log holds at most 500 entries and only the last 90 days
reach the feed, so old entries can be deleted when it fills.

### The watcher's limits

The watcher reads the issuer's public card page, which is marketing
copy for people who do not have the card yet. It catches a benefit
being added and stated changes to amount, cadence and enrollment.
Fine-print terms that are not on that page are not checked.

The page leaves out benefits that cardholders still have, so the
commit job refuses an update that removes one or strips its schedule.
When a benefit stops appearing on the page, the watcher adds a note to
the change log, once, saying so. Removing a benefit that has really
ended is a hand edit to `data/benefits.yaml`.

The schema limits what data can put in a calendar: bounded lengths, no
control or direction-override characters, and no links, web addresses or
email addresses in any text an event shows. Plain-text wording still
comes from an unattended model reading a web page; treat an event that
asks for anything unusual as suspect and check your account instead.

### Setting up the watcher in a fork

Give the watcher one credential, as repository secrets. The first one
configured is used:

1. `ANTHROPIC_API_KEY`: an Anthropic API key.
2. Workload identity, which stores no key at all: each run trades its
   GitHub identity token for an access token that lasts minutes. In the
   Claude Console, connect a GitHub Actions workload with a rule for
   this repository's `main` branch, then set the ids it gives you:
   `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`,
   `ANTHROPIC_SERVICE_ACCOUNT_ID` and, if the rule covers more than one
   workspace, `ANTHROPIC_WORKSPACE_ID`. The ids are not credentials;
   they are secrets only to keep them out of the public run logs.

   The rule's subject must be exactly what GitHub sends, which carries
   numeric ids:
   `repo:<owner>@<owner id>/<repo>@<repo id>:ref:refs/heads/main`. The
   surest way to get it right is to run the watcher once and copy the
   subject from the refused attempt in the Console's authentication
   history.

   Any step of the `watch` job can obtain that access token, which is
   why the job runs so little. Narrow the rule further by also matching
   the token's `job_workflow_ref` claim to
   `<owner>/<repo>/.github/workflows/watch.yml@refs/heads/main`.
3. `CLAUDE_CODE_OAUTH_TOKEN`: from `claude setup-token`, which uses a
   Claude subscription.

Enable GitHub Pages with "GitHub Actions" as the source. The workflow
pushes straight to `main` as `github-actions[bot]`, so `main` must not
require pull requests. A ruleset that blocks force pushes and deletion
and requires linear history works with it; one that requires signed
commits does not, because the workflow's commit is unsigned.

Prefer workload identity, in a workspace with a low spend limit. The
model reads a web page while its credential is within reach of its
process. Its tools give it no way to read the environment or anything
outside the checkout, and the files it writes are screened for anything
shaped like a key, but a token that expires in minutes is a safer thing
to have there than a key, and either is safer than a subscription token
that covers the whole account for a year.

The model tool's version is pinned in `watcher/package-lock.json`. The
restrictions in `scripts/run-watcher.sh` were checked against that
version; check them again before accepting an update to it.

### When the watcher run fails

A failed run changes nothing; the published feed stays as it was and
the next month's run tries again. The log names the failing step:

- **Download the issuer's page** or **Reduce it to text**: the issuer
  blocked the request or changed the page beyond recognition.
- **Compare the data with the page**: no credential is configured, it
  is invalid or out of quota (for workload identity, the Console's
  authentication history says why an exchange was refused), or the
  model stopped early.
- **Screen the data files** or **Take the two data files and nothing
  else**: the model left the data untouched, or wrote something that is
  not acceptable.
- **Validate, rewrite, build and test**: the model's edit broke the
  schema, removed a benefit or its schedule, or did not set `verified_on` to the day of
  the run. Make the change by hand if it is real.
- **Commit the data to main**: `main` moved while the run was in
  progress. Run the workflow again.

GitHub turns scheduled workflows off after 60 days without repository
activity. The monthly data commit normally prevents that; if the watcher
has been failing for two months, re-enable the workflows from the
Actions tab after fixing it.

## Develop

Requires [uv](https://docs.astral.sh/uv/) and
[shellcheck](https://www.shellcheck.net/).

```sh
uv sync
uv run pre-commit install
uv run perkolator validate
uv run perkolator build
uv run pytest --cov=perkolator
uv run ruff format . && uv run ruff check . && uv run mypy src tests
```

`perkolator build` writes `_site/amex-platinum.ics`, which git ignores;
`--out` chooses another path. `perkolator build --today YYYY-MM-DD`
builds for a fixed date, which must
not be earlier than the catalog's `verified_on` or any change's
`detected_on`. Invalid data, including a date after the build date,
exits with status 1 and leaves the existing feed untouched.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Licence

MIT; see `LICENSE`. The benefit names and terms described in `data/`
belong to their issuer.
