<!-- sourced from: addyosmani/agent-skills (interview-me), trimmed examples/verification for brevity, mechanism kept intact -->
---
name: interview-me
description: >
  Extract what's actually wanted before building it, one question at a time
  with a guess attached, until confident. Use when a request is
  underspecified, or when the user explicitly says "interview me" or
  "are we sure about this".
---

# Interview Me

What people ask for and what they actually want differ. The cheapest moment
to close that gap is before any plan or code exists.

Skip this for unambiguous, self-contained asks, or when the user has asked
for speed over verification.

## Step 1: hypothesize with a confidence number

```
HYPOTHESIS: <one sentence, your current best read>
CONFIDENCE: ~NN% -- <what's missing, if below ~70%>
```

## Step 2: one question at a time, each with a guess

```
Q: <one focused question>
GUESS: <your hypothesis for the answer, with the reasoning>
```

Wait for a reaction before the next question. Batching questions gets
skim-read answers. A guess gets a faster, more honest reaction than an
open question does.

## Step 3: watch for "want" vs "should want"

Buzzword answers ("scalable", "modern", "the standard approach") are a
signal to push once more: "if you didn't have to justify this to anyone,
what would you actually want?"

## Step 4: restate and confirm

```
- Outcome:      ...
- Who it's for: ...
- Why now:      ...
- Success:      ...
- Constraint:   ...
- Out of scope: ...

Yes / no / refine?
```

"Sounds good" or silence is not a yes, ask explicitly if anything needs
refining.

## Stop condition

Can you predict the reaction to the next three questions you'd ask? If yes,
stop and restate. If not, ask more. If several rounds in and still can't
predict it, say so, something foundational is missing, don't keep grinding.
