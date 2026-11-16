# UK Spider Stock Tracker

Checks UK tarantula shops twice a day (about 07:40 and 18:40). It keeps one combined stock page and sends your phone an alert when a new tarantula is listed or one comes back in stock.

- **Stock page:** `https://ryannett94.github.io/tarantula-stock/`
- **Alerts:** the free **ntfy** app (iOS and Android)
- **Shops checked:** listed in `vendors.yml`

## One-time setup (about 10 minutes, easiest on a computer)

1. **Make the repo.** On GitHub, create a new **public** repository called `tarantula-stock`. GitHub Pages and Actions are free for public repos. Upload everything in this folder, including the hidden `.github` folder. Drag-and-drop on the GitHub website works.
2. **Set up phone alerts.** Install **ntfy** from the App Store or Play Store, tap **+**, and subscribe to the topic
   `ryan-tstock-458e621b`
   Anyone who knows the topic name can read the alerts, so keep it to yourself.
3. **Give the tracker the topic.** In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**. Set Name to `NTFY_TOPIC` and Value to `ryan-tstock-458e621b`.
4. **Turn on the page.** Go to **Settings → Pages**. Set Source to **Deploy from a branch**, Branch to **main**, and Folder to **/docs**, then save.
5. **Allow the bot to save results.** Go to **Settings → Actions → General → Workflow permissions** and pick **Read and write permissions**, then save.
6. **First run.** Go to **Actions → Check tarantula stock → Run workflow**. The first run records what every shop has now and sends no alerts. From then on, you only hear about new stock.

## Checking it's working

At the bottom of the stock page, open **Shops checked**. It shows each shop as working, with its stock count, or as failed, with the reason. If a shop fails:

- Open that shop on your phone and go to its tarantula page.
- Copy the URL and paste it under that shop's `listings:` in `vendors.yml`. The pencil icon on GitHub lets you edit the file.
- The next run picks up the change.

## Changing things

- **Add or remove a shop:** edit `vendors.yml`.
- **Check times:** edit the `cron` lines in `.github/workflows/check-stock.yml`. The times are in UTC.
- **Check right now:** go to Actions → Run workflow.

## How it reads shops

For each shop it tries three methods in order:

1. The Shopify product feed.
2. The WooCommerce store feed.
3. Loading the shop's tarantula pages in a real browser and reading the product cards.

Only tarantulas are kept. It matches on the category, the word "tarantula", or a known genus, and skips setups, tubs and other kit.

GitHub may pause scheduled runs if a repo has no activity for 60 days. Because the bot commits stock updates, that shouldn't happen. If it ever does, the Actions tab shows a button to turn it back on.
