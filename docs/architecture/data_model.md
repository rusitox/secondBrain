# Data Model: Memory & Identity

## Relational Schema
### Users
- `id`: UUID (PK)
- `email`: String
- `preferences`: JSONB (Global settings)

### KnowledgeItems (The "Facts")
- `id`: UUID (PK)
- `user_id`: FK -> Users
- `content`: Text (The fact)
- `category`: String (preference, work, health, etc.)
- `importance`: Int (1-5)

## Vector Schema
### Memories (Semantic Store)
- `id`: UUID (PK)
- `user_id`: FK -> Users
- `content`: Text
- `embedding`: Vector(1536) (Cosine distance)
- `metadata`: JSONB (source, timestamp)

## Sync Strategy
- **Write**: New interactions -> LLM Extraction -> Vectorization -> Storage.
- **Read**: Query -> Vectorization -> Similarity Search -> Prompt Injection.
