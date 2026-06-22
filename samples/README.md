# Samples — drop your decks and collection here

This is where you bring your own data into MTG Analyzer. Export from your usual tools and drop the
files in this folder, then ask Claude Code to load them (or run the commands yourself).

- **Decklists** (`.txt`) — from Archidekt (Export → Text), Moxfield, MTG Arena, or MTGO.
  ```
  mtg deck show samples/MyDeck.txt
  mtg deck save "My Deck" samples/MyDeck.txt   # save it so you can refer to it by name
  ```
- **Collection** (`.csv`) — from ManaBox (Export Collection), or Moxfield/Archidekt/Deckbox.
  ```
  mtg inventory import samples/collection.csv
  mtg inventory show --card "Sol Ring"
  ```

Or just tell Claude Code: *"Import my collection from `samples/collection.csv`"* or *"Analyze my
deck in `samples/MyDeck.txt`."*

**Your privacy:** every file you put here is **gitignored** — only this README is tracked. Your
decks and collection stay on your machine and are never committed or pushed.

