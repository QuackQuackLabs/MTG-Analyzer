# Samples

Drop your real exports here to test the importers against actual data:

- **Decklists** (`.txt`) — from Archidekt (Export → Text), Moxfield, MTGA, or MTGO.
  ```
  mtg deck show samples/my-deck.txt
  ```
- **Collection** (`.csv`) — from ManaBox (Export Collection), or Moxfield/Archidekt/Deckbox.
  ```
  mtg inventory import samples/my-collection.csv
  mtg inventory show --card "Sol Ring"
  ```

The export files themselves are **gitignored** (personal data) — only this README is tracked.
Real exports have quirks synthetic fixtures miss, so adding a couple here is the best way to
harden the parsers.
