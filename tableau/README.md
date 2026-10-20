# Tableau Public version

Four charts and one dashboard built from the three CSVs in this folder. About 1–1.5 hours the first time.

| File | One row per | Used for |
|---|---|---|
| `companies.csv` | company (25) | margin change bars, commitments bars |
| `cost_lines.csv` | company × cost line (125) | cost-structure heatmap |
| `quarterly.csv` | company × quarter (603) | margin trend line |

To refresh the files after rebuilding the warehouse: `python tableau/export_tableau.py`.

---

## 0. Install and connect (10 min)

1. Go to [public.tableau.com](https://public.tableau.com), click **Sign Up**, and make a free profile.
2. On the same site, click **Create → Download Tableau Public** (the desktop app), then install and open it.
3. Under **Connect → To a File**, click **Text file** and pick `tableau\companies.csv`.
4. Add the other two files as separate data sources: top menu **Data → New Data Source → Text file**,
   pick `cost_lines.csv`; repeat for `quarterly.csv`.
5. Click **Sheet 1** at the bottom left to start.

Tip: in the left **Data** pane, pick which file you're using from the list at the top. Dimensions (text) are
at the top of the field list and measures (numbers) at the bottom.

---

## 1. "Margin change since FY2022" (15 min) — data source: companies

1. Rename the sheet: double-click the **Sheet 1** tab, type `Margin Change`.
2. Drag **Company** to **Rows**.
3. Drag **Gross Margin Change (bps)** to **Columns**. You'll get horizontal bars.
4. Drag **AI Disclosure** onto **Color** in the Marks card.
5. Sort: click the small sort icon in the toolbar (**Sort descending**) so the biggest gains are on top.
6. Hide C3.ai, whose −4,570 bps drop squashes everything else: right-click its bar → **Exclude**.
7. Set the colors: click **Color → Edit Colors…**, then click each value and pick a color on the right:
   - *Says AI is raising costs now* → red
   - *Lists AI as a risk only* → orange
   - *Not mentioned* → gray
8. Drag **Gross Margin Change (bps)** onto **Label** to print the number on each bar.
9. Hover tooltip: drag **FY2022 Gross Margin %**, **TTM Gross Margin %** and **AI Cost Trend** onto **Tooltip**.
10. Title: double-click the title, write `Gross margin rose at 18 of 25 companies, including 4 of the 5 that say AI is raising their costs`.

---

## 2. "Where the money went" heatmap (15 min) — data source: cost_lines

1. Click the **New Worksheet** icon (bottom, next to the sheet tabs). Rename it `Cost Structure`.
2. Drag **Cost Line** to **Columns** and **Company** to **Rows**.
3. In the Marks card, change **Automatic** to **Square**.
4. Drag **Change (pts)** onto **Color**, then drag it again onto **Label**.
5. Fix the column order: right-click **Cost Line** on Columns → **Sort…** → **Sort By: Field**,
   **Field Name: Line Order**, **Aggregation: Sum**, **Ascending**.
6. Hide operating margin here (it's a result, not a cost): right-click its column header → **Exclude**.
7. Hide C3.ai: right-click the C3.ai row label → **Exclude**.
8. Colors: **Color → Edit Colors…** → Palette **Orange-Blue Diverging**, tick **Reversed**, tick
   **Use Full Color Range**, then **Advanced >>** → tick **Center** and type `0`. Blue now means the cost
   fell as a share of revenue, orange means it grew.
9. Title: `AI was paid for with people: sales & marketing fell the most`.

---

## 3. "Gross margin by quarter" (15 min) — data source: quarterly

1. New worksheet, rename `Margin Trend`.
2. Drag **Quarter End** to **Columns**. Click the arrow on the green/blue pill → choose the **second
   Quarter** option (the one showing `Q2 2015` style, which turns the pill green = continuous).
3. Drag **Gross Margin %** to **Rows**. Click its arrow → **Measure → Average**.
4. Drag **Company** to **Filters** → pick **Adobe** only → OK. Then right-click the Company pill in Filters
   → **Show Filter**. On the filter card's arrow (top right), choose **Single Value (dropdown)**.
5. Baseline line: drag **FY2022 Gross Margin %** onto **Detail**. Open the **Analytics** tab (top left, next
   to Data) → drag **Reference Line** onto the chart → drop on **Pane** → Value: **AVG(FY2022 Gross Margin %)**,
   Label: **Custom** → type `FY2022 baseline`, line style dashed → OK.
6. Right-click the vertical axis → **Edit Axis…** → untick **Include zero**.
7. Title: `Gross margin by quarter vs FY2022 baseline`.

---

## 4. "Cloud commitments" (10 min) — data source: companies

1. New worksheet, rename `Commitments`.
2. Drag **Company** to **Rows**, **Commitments % of Revenue** to **Columns**, **AI Disclosure** to **Color**.
3. Remove companies with no data: drag **Commitments % of Revenue** to **Filters** → **All values** →
   Next → **Special** tab → **Non-null values** → OK.
4. Sort descending; drag **Purchase Commitments ($M)** onto **Label** and **Purchase Commitments FY2022 ($M)**
   onto **Tooltip**.
5. Title: `Cloud commitments: up from $13.6B to $25.7B since FY2022 (11 companies with both years)`.

---

## 5. Dashboard (15 min)

1. Click the **New Dashboard** icon (bottom, middle icon). Rename it `Is AI eating SaaS margins?`.
2. Left panel → **Size** → **Fixed size**, width `1400`, height `1000`.
3. Drag sheets from the left list onto the canvas:
   - **Margin Change** on the left half
   - **Cost Structure** on the top right
   - **Margin Trend** on the bottom right
   - **Commitments** under Margin Change, or as a separate dashboard if it's crowded
4. Click a company to update the trend line: top menu **Dashboard → Actions… → Add Action → Filter…**
   - Source sheet: **Margin Change**, Run action on: **Select**
   - Target sheet: **Margin Trend**
   - Target filters: **Selected Fields** → Source field **Company**, Target field **Company**
   - Clearing the selection will: **Show all values** → OK
   Then remove the Company filter card from Margin Trend if it shows up on the dashboard (click it → **x**).
5. Add a title: tick **Show dashboard title** at the bottom left. Drag a **Text** object under it and write:
   `Source: SEC 10-K/10-Q XBRL filings for 25 public SaaS companies, FY2022 vs trailing twelve months to mid-2026. Full analysis: <your Streamlit link>`.

---

## 6. Publish (5 min)

1. **File → Save to Tableau Public As…**, sign in, name it `Margin Squeeze - Is AI eating SaaS margins`.
2. It opens in your browser. Click the **gear/settings icon** → make sure **Show Viz on Profile** is on.
3. Copy the URL and send it to me; I'll add it to the main README.

## Common snags

- **Bars show `SUM(...)` that look too big:** a field got summed across rows. Click its pill → **Measure → Average**.
- **Quarter End shows only years:** click the pill arrow and pick the lower (green) **Quarter** option.
- **The filter action does nothing:** check the field mapping in step 5.4 uses **Company** on both sides.
- **"Save to Tableau Public" is the only save option:** that's normal for the free version; workbooks are public.
