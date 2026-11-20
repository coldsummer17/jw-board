# Doc Job Workstation — setup guide

Your workstation runs for free on GitHub:

- **GitHub Actions** runs the job fetcher at **09:00 and 22:00 Beijing time** every day (GitHub usually starts runs a few minutes late, so results arrive around then).
- **GitHub Pages** hosts the dashboard at `https://<your-username>.github.io/<repo-name>/`.
- The job data is **encrypted with your password**. The page is public, but without the password nobody can see the jobs, and search engines are told not to index it.

You do this setup once (about 15 minutes). After that, nothing needs your computer to be on.

---

## 1. Create the repository

1. Sign in at [github.com](https://github.com) (you use "Continue with Google").
2. Click **+** (top right) → **New repository**.
3. Name: `doc-job-workstation` (or anything you like; it becomes part of the web address).
4. Choose **Public**. Free GitHub Pages needs a public repository. Your job data stays encrypted, and the code holds no personal details.
5. Leave "Add a README" unticked. Click **Create repository**.

## 2. Upload the files

Upload everything in this folder **except** `Resume/`, `.venv/` and any `docs/data.json`:

`config.json`, `requirements.txt`, `SETUP.md`, `README.md`, `.gitignore`, the `fetcher/` folder, the `docs/` folder, and the `.github/` folder.

Easiest way (no tools needed): on the new repository page, click **uploading an existing file** and drag the files and folders in. Then click **Commit changes**.

> The `.github` folder is hidden in Finder. Press **Cmd + Shift + .** in Finder to show hidden files so you can drag it in.
> If it still won't upload: in the repository click **Add file → Create new file**, type `.github/workflows/update-jobs.yml` as the file name (the slashes create the folders), paste in the contents of that file from this folder, and click **Commit changes**.

## 3. Set your password (repository secret)

1. In the repository: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `SITE_PASSWORD`. Value: a password you'll type to open the dashboard. Use something long that you don't use anywhere else.
3. Click **Add secret**.

## 4. Allow the workflow to save results

**Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → **Save**.

## 5. Turn on GitHub Pages

**Settings → Pages → Build and deployment**:
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/docs** → **Save**

After a minute, the page shows your site address, e.g. `https://yourname.github.io/doc-job-workstation/`. Bookmark it on your laptop and phone.

## 6. Run it the first time

**Actions** tab → if asked, click **"I understand my workflows, go ahead and enable them"** → choose **Update job pool** → **Run workflow** → **Run workflow**.

The first run takes about 10–15 minutes. When the run shows a green tick, open your site, enter the password, and your jobs are there. From then on it updates by itself twice a day.

---

## Everyday use

- **Sort**: Best fit (default) or Most recent.
- **Filters**: My status, Date posted, Workplace type, Employment type, Location (region + city/country text), Source.
- **Save / Applied / Dismiss / Note** on each job. Dismissed jobs are hidden unless you pick "Dismissed" or "Everything" under My status.
- **Export CSV** downloads the jobs currently shown, with your status and notes.
- **Your marks and notes are stored in the browser you use.** To move them between laptop and phone, use **Back up my marks** on one device and **Restore** on the other.
- When a new update lands, an orange banner tells you how many new jobs arrived, and **Show new jobs** filters to just those. If the page is open during an update, a "Reload" message appears.
- **Quick links** tab: boards that can't be read automatically (Mandy, Staff Me Up, BOSS直聘, 猎聘, 拉勾, fixer directories…).
- **Sources** tab: what each source returned in the last update, including any that were blocked.

## Changing things later

Everything adjustable is in **`config.json`**. Edit it on github.com (open the file → pencil icon → **Commit changes**). Saving it triggers a fresh run automatically.

| To change… | Edit this part of `config.json` |
|---|---|
| What counts as a good fit | `scoring` (role words, China/Mandarin words, penalties) |
| How strict the relevance cut-off is | `min_fit_score` (higher = fewer, more relevant jobs) |
| How long jobs are kept | `keep_days` |
| Turn a source on/off | `sources` → `"enabled": true/false` |
| JobSpy master switch | `jobspy` → `"enabled": true/false` |
| A single JobSpy site (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google) | `jobspy` → `sites` |
| JobSpy search words and places | `jobspy` → `search_terms`, `searches` |
| Employer watchlist | `sources` → `watchlist` → `employers` |
| Filter options shown on the page | `filters` |
| Quick links | `quick_links` |

Changing the update times means editing the two `cron` lines in `.github/workflows/update-jobs.yml`. They're in UTC: Beijing time minus 8 hours.

## Optional extra sources (free API keys)

These are switched on in `config.json` but stay idle until you add the keys as repository secrets (same place as `SITE_PASSWORD`):

- **Adzuna**: free key at developer.adzuna.com → secrets `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
- **Jooble**: free key at jooble.org/api/about → secret `JOOBLE_KEY`.

## Notes and limits

- ZipRecruiter, Google Jobs and sometimes Glassdoor block requests from GitHub's servers. When that happens the Sources tab shows it in red, and the other sources still work.
- GitHub pauses scheduled workflows in repositories with no activity for 60 days. The twice-daily result commits count as activity, so this shouldn't happen. If it ever does, the Actions tab shows a button to re-enable it.
- To change your password, update the `SITE_PASSWORD` secret and run the workflow once. On each device, click **Lock** and enter the new password.
