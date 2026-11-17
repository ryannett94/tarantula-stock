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
- **Check right now:** tap **Update now** at the top of the stock page (see below), or go to Actions → Run workflow.
- **Fix a shop's mistake** (wrong name, size or sex on a listing, or something that isn't a spider): add an entry to `corrections.yml`. The file explains the format.

## Update now button

The page is a static site, so the button asks GitHub to run the checker straight away, waits for it (about 3–4 minutes for all 19 shops, run side by side), and then loads the fresh results directly from the repo.

It needs a GitHub token, entered once per browser. The page shows these steps the first time you tap it:

1. Open github.com → Settings → Developer settings → Fine-grained tokens → Generate new token.
2. Repository access: **Only select repositories** → `tarantula-stock`.
3. Permissions: **Actions: Read and write** and **Contents: Read-only**. Nothing else.
4. Paste it into the box on the page.

The token is kept only in that browser's storage and can only start this checker and read this repo. A "Remove saved token" link is under the box.

## Shops that only publish a price list

MARPC lists prices but says to phone to check availability, and marks nothing as sold out. Its listings are never shown as in stock and never alert. In the **All** tab they show **Phone ›** with the date the shop last updated its list. This is set with `stock: unconfirmed` on the shop in `vendors.yml`.

## Filters on the page

- **Spider type:** tarantulas, jumping spiders, true & other spiders
- **Lifestyle:** arboreal, terrestrial, fossorial / burrowing, trapdoor. This comes from a researched genus/species table in `tracker/lifestyle.py`, which wins over what the shop prints, because shops sometimes get it wrong. A shop's own label is used only for a genus the table doesn't know. Opportunistic burrowers get both terrestrial and fossorial. Species that dig as slings and climb as adults, like *Phormingochilus hatihati*, get arboreal and fossorial.
- **Size:** slings, juveniles, sub-adults, adults. This comes from the listing name, size option or description; the "adult size" shown on care sheets is ignored.
- **Sex**, **shop**, and search by scientific or common name

The same species from different shops is shown as one card. Spelling slips and old names are merged, and current names follow the World Spider Catalog. For example, *Haplopelma/Cyriopagopus schmidti, lividus, albostriatus, minax* are now *Melopoeus*, *Orphnaecus philippinus* is now *Selenobrachys*, *Thrixopelma lagunas* is now *Warmiru lagunas*, and the hobby's *Cyriopagopus* sp. "Hati Hati" and *Phormingochilus* sp. "Rufus" are now *Phormingochilus hatihati* and *Aspinochilus rufus*.

## Species pages and photos

Tap a species card (the photo or name) to open its page:

- **Gallery:** openly licensed photos from iNaturalist, each credited to its photographer, plus the shops' own listing photos. A shop photo that appears on more than one species is treated as a logo or stock image and left out. For hobby forms without a formal name (`Genus sp. "Locality"`), the shops' photos come first and any iNaturalist photo is labelled **GENUS PHOTO**, because it shows the genus, not that exact form. Tap a photo to see it large.
- **Where it's from:** countries with research-grade wild records on iNaturalist. Captive records are left out.
- **Defence & bite** and **Keeping:** general notes for the spider's group (New or Old World tarantula subfamily, or spider family) and its lifestyle. These aren't a full care sheet.
- **About:** the Wikipedia summary, with the link.
- **Where to buy:** every current listing.

The info is built by `tracker/enrich.py` into `docs/species.json`. Each check looks up up to 25 new species, and entries refresh every 60 days.

Lifestyle chips can be combined. Tick Arboreal and Fossorial to see species that are either.

## Quality check

`python tracker/qc.py docs/stock.json 7` opens a random sample of real product pages from every shop and checks that the recorded price is on the page and that in-stock or sold-out matches. It also checks each listing's species against its own name.

## How it reads shops

For each shop it tries three methods in order:

1. The Shopify product feed.
2. The WooCommerce store feed.
3. Loading the shop's tarantula pages in a real browser and reading the product cards.

Only tarantulas are kept. It matches on the category, the word "tarantula", or a known genus, and skips setups, tubs and other kit.

GitHub may pause scheduled runs if a repo has no activity for 60 days. Because the bot commits stock updates, that shouldn't happen. If it ever does, the Actions tab shows a button to turn it back on.
