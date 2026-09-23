# Food Radar KZ

Small Python monitor for public Instagram and Threads posts about restaurant events, promotions, food news, HoReCa and FoodTech in Almaty, Astana and Kazakhstan. It fetches results through Apify, filters them with transparent rules, stores new posts in SQLite and exports JSON or CSV. Python 3.10+; no runtime packages.

## Quick start

```bash
cp config.example.json config.json
python3 -m food_radar collect --dry-run
export APIFY_TOKEN='your Apify API token'
python3 -m food_radar collect --max-runs 8 --max-charge-usd 0.10
python3 -m food_radar export --out exports/posts.csv
```

`--max-runs` limits Actor calls in one invocation; `--max-charge-usd` caps each Actor run. With the sample config and defaults, the maximum charge for one invocation is $0.80. Daily runs at that maximum would exceed the $5 monthly Free plan credit; reduce sources/frequency or caps to fit your budget. Apify may still charge for useful results that fail the local relevance filter. Actor prices and platform rules can change. Check the [Apify pricing page](https://apify.com/pricing) before scheduling frequent runs. The program does not store or print the token; never commit it.

Edit `config.json` to add public Instagram usernames to `instagram_profiles`, city-specific hashtags to `instagram_hashtags`, and search strings to `threads_queries`. Each Instagram profile, hashtag and Threads query is one Actor run. The first `--max-runs` jobs are executed in that order, so increase the limit to cover the whole config. `source_cities` maps a known username or source to `almaty` or `astana` when a post omits the city. For example:

```json
"source_cities": {"example_cafe": "astana"}
```

The sample config leaves account names empty because it should not silently follow unverified businesses. It includes two example hashtags and six search queries. Review and replace these with sources that produce useful results. A dry run shows what would run without sending requests.

If you already have a JSON dataset exported from either Actor, import it without an API token:

```bash
python3 -m food_radar ingest threads-export.json --platform threads --source 'Алматы ресторан'
python3 -m food_radar ingest instagram-export.json --platform instagram --source '#алматыеда'
python3 -m food_radar export --city almaty --category event --out exports/almaty-events.json
```

## How it decides

A post needs a food/restaurant term and a city in the text, Instagram location, trusted `source_cities` mapping, or the configured Instagram hashtag. Kazakhstan-wide industry posts are assigned `kazakhstan`. Event, promotion, industry and general food news are distinguished by keyword rules. An explicit event date such as `28.09.2026` or `28 сентября` is extracted when present; events with an explicit past date are skipped using Almaty/Astana time. Missing dates remain empty. Posts older than 14 days are skipped by default; change `max_post_age_days` in the config. SQLite prevents duplicate platform IDs and URLs. UTM parameters are removed before saving.

This is a lead discovery feed, so review an original post before publishing its date, price or terms. The parser currently reads text captions; event posters containing details only in an image need OCR. It does not find all relevant posts or infer the date of a promotion from phrases such as “until Sunday.” It does not combine separate posts about the same real-world event.

## Sources and limits

- Instagram: [Apify Instagram Scraper](https://apify.com/apify/instagram-scraper), using public profile or hashtag URLs.
- Threads: [The Mine Works Threads Scraper](https://apify.com/themineworks/threads-scraper), using recent keyword search.
- API transport: [Apify synchronous Actor endpoint](https://docs.apify.com/api/v2/actors-actor-runs). The sync endpoint has a five-minute run limit; a timeout may leave the remote run's status unknown. Review the Apify console before retrying such a run.

Actor input/output schemas may change. Both third-party Actors should be checked with one small live run after configuring a token. The code and tests can be exercised offline using `ingest` or test fixtures, but this repository has not been validated against a live Apify account.

Run tests with `python3 -m unittest discover -s tests -v`.
