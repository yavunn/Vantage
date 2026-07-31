"""RAG (retrieval-augmented generation) katmanı.

Kaynak DAİMA normalize şemadır (commits / pull_requests / tasks). Kaynak
sistemlere (GitLab, Trello, Jira) doğrudan istek atılmaz — ingest zaten
çekiyor. Böylece yeni bir adaptör eklemek RAG'ı hiç değiştirmez; adaptör
deseninin amacı budur.
"""
