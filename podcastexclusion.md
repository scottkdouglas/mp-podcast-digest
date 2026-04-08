# Episode Exclusion Rules

These rules tell the summarizer what parts of each episode to KEEP versus DROP when generating the summary and the trimmed transcript.

## Episode structure

Every episode follows roughly this pattern:

1. **Cold open** — Matt teases the topic of the episode in his own words. Variable each episode. **KEEP.**
2. **Fixed marketing intro** — Matt reads the same scripted intro that begins with: "My goal is to help. To help restaurant owners finally get to where they want to go. But more than that, my goal is to find entrepreneurs within that segment that actually know what it means to hustle." It typically ends with "Restaurant Marketing Secrets, Episode [number]." **DROP.**
3. **Opening sponsor read (ABR)** — Right after the episode number, Matt introduces himself ("I'm your host, Matt Plapp") and does a "brought to you by" sponsor read for America's Best Restaurants. It begins with phrasing like "And like always, we're brought to you by America's Best Restaurants" and typically lists what ABR helps independent restaurants "win" (new customers, lost customers, more frequent customers, increased check averages, their community, etc.). It usually ends with a phrase about winning against the chains. **DROP everything from "I'm your host" through the end of the ABR sponsor read.**
4. **Main content** — the actual episode body. Begins after the ABR sponsor read ends, typically with Matt starting a fresh thought related to the day's topic. **KEEP.**
5. **Skool community promotion** — Matt closes by inviting listeners to join his Skool community, group, or coaching program. The exact wording varies every episode. Anytime Matt pivots away from the topic into a "join my community" or "come learn from me" sales pitch, that is the outro. **DROP everything from that pivot to the end of the episode.**

## Output requirements

The trimmed transcript must be split into two subsections:

- **Cold Open** — the topic teaser at the very start (item 1 above)
- **Body** — the main content (item 4 above)

Items 2 (marketing intro), 3 (ABR sponsor read), and 5 (Skool promotion) must not appear anywhere in the output — not in the transcript, not in the quotes, not in the insights.

## Edge cases

- If you cannot tell where the cold open ends and the marketing intro begins, prefer to keep LESS in the Cold Open section. The marketing intro is the unmistakable scripted boilerplate that always starts with "My goal is to help."
- If an episode has no cold open and jumps straight into the marketing intro, leave the Cold Open subsection empty rather than misclassify content.
- If you cannot clearly identify where the ABR sponsor read ends and the body begins, look for the transition where Matt stops listing what ABR helps restaurants "win" and starts a new thought tied to the day's topic. That transition is the start of the body.
- If you cannot clearly identify where the Skool outro begins, include the rest of the episode in the Body rather than drop content speculatively. Err on the side of keeping main content.
- Never invent, paraphrase, or "clean up" Matt's spoken words. Use exact transcription for the Cold Open and Body subsections.
