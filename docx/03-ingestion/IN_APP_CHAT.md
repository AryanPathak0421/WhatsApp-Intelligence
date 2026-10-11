# In-app chat (team groups and direct messages)

People talk to each other inside the application. No WhatsApp number, no Meta API, no external service: the messages live in this system's own database.

## What it is
| | Group with a project | Group without a project | Direct message |
|---|---|---|---|
| Members | people with access to that project (clients included) | internal users only | exactly two internal users |
| Analysed | **yes**: every message is mirrored into the project chat, so tasks, progress, health and summaries update from live conversation | no | no, never |
| Created by | admin / project manager with edit access | admin / project manager | any internal user |

Client accounts (`CLIENT_VIEWER`) can write in project groups they were added to; they cannot start direct messages or groups and see only their own project's groups.

## How a message flows
```
POST /api/rooms/:id/messages  -> RoomMessage (the chat itself)
   |-- project group: also ChatMessage (id "<project>:app_<id>", seq next, sender = ChatParticipant linked to the user)
   |        -> debounced re-analysis (`ANALYSIS_DEBOUNCE_MS`, default 30 s; one job per burst)
   '-- SSE event "chat.message" {roomId, userIds[]}  (ids only, delivered to room members only)
client refetches /rooms and /rooms/:id/messages (60 s polling fallback if the stream is down)
```
The sender is matched to an existing participant of the project by account link, then by display name (so a person who already appears in messages stored by the former WhatsApp import stays one person), else a participant is created.

## API (all need sign-in; a room that is not yours answers 404)
| Route | Notes |
|---|---|
| `GET /rooms` | my rooms with last message and unread count; project rooms disappear if the project access is lost |
| `POST /rooms` | `{name, projectId?, memberIds[]}`; needs `member:manage` and project edit |
| `POST /rooms/direct` | `{userId}`; one room per pair (201 new, 200 existing) |
| `GET /rooms/:id`, `PATCH /rooms/:id` | details with members; rename (creator/admin) |
| `GET /rooms/:id/messages?before&limit` | oldest-first page, `hasMore`; replies carry a quoted snippet |
| `POST /rooms/:id/messages` | `{text<=4000, replyToId?}`; 60 messages per minute per user; a reply can only point inside the same room |
| `POST /rooms/:id/read` | marks read (drives the unread counts) |
| `POST /rooms/:id/members`, `DELETE /rooms/:id/members/:uid` | creator/admin adds or removes; anyone can leave; people must have project access to join a project group |
| `GET /room-users?projectId=` | who the caller may add / message (empty for client accounts) |

## E-mail invitations (SMTP)
- **Existing account** added to a group (at creation, through "Add people", or by e-mail address): it joins at once and receives a notice e-mail with a link to the chat. The person who added them is never e-mailed.
- **No account yet** (typically a client), project groups only: `POST /rooms/:id/invite {email, name?}` e-mails a single-use link `FRONTEND_URL/invite/<token>`.
  Opening it shows who invited them to which group; they choose a name and password, and the system creates a `CLIENT_VIEWER` account with **view** access to that project and membership of the group, then signs them in.
- Who can invite: the group's creator or an admin, with edit access to the project (the invitation grants project access). 30 invitations per hour per person.
- Tokens: 48 random bytes, only the SHA-256 is stored, expire after `INVITE_TTL_DAYS` (7), single use (also under a race), a newer invitation to the same address revokes the older link, managers can list and revoke pending invitations (`GET/DELETE /rooms/:id/invites`).
- If an account with that e-mail already exists when the link is opened, nothing is created: the page asks them to sign in.
- E-mails escape every user-provided name; no address is written into the audit log; send failures are logged without the body or the token.
- Without `SMTP_HOST` nothing is sent; the invitation is still created and the response says `emailSent: false`.

| Variable | Meaning |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` (465), `SMTP_SECURE` (true) | SMTP server; Gmail: `smtp.gmail.com`, 465, secure |
| `SMTP_USER`, `SMTP_PASS` | account and **app password** (Google account → Security → App passwords; needs 2-step verification). Keep only in the environment (dev: `private-data/dev.env`) |
| `SMTP_FROM` | sender shown to recipients, default `Project Intelligence <SMTP_USER>` |
| `INVITE_TTL_DAYS` | invitation link lifetime (7) |
| `FRONTEND_URL` | base of the links in e-mails; must be the address recipients can open (in production the public HTTPS URL, not localhost) |

Gmail limits a personal account to about 500 recipients a day; a company domain or a transactional mail service is the production choice.

## Privacy rules
- Direct messages are private to the two people: **even admins cannot read them** through the API, and they are never analysed or mirrored.
- Live events contain ids only, never message text, and are delivered only to room members.
- Retention and erasure of a project also delete its in-app group messages (`RoomMessage` and the mirrored `ChatMessage`). A project group's DMs do not exist, so nothing else is affected.
- Messages are stored in plain text in `RoomMessage` (not field-encrypted like phone numbers); database-level encryption at rest applies as for the rest of the application.

## Not implemented
Attachments and voice notes, message edit/delete, reactions, read receipts per person (ticks turn blue only when everyone has read), online/last seen, push notifications, end-to-end encryption.
Implemented since the first version: typing indicator (`POST /rooms/:id/typing`, ephemeral, other members only), search inside a chat (client-side), unread divider, optimistic send.
Mentions are plain text for now.

## Code and tests
`backend/src/services/rooms.ts`, `backend/src/controllers/rooms.ts`, tables `ChatRoom`, `RoomMember`, `RoomMessage` (migration `20261009010000_inapp_chat`), frontend `pages/Chat.tsx`.
`backend/tests/rooms.test.ts`: 13 tests (incl. read ticks); `backend/tests/invites.test.ts`: 8 tests (link, accept, single use, replace/revoke/expiry, who may invite, existing accounts, notices, no-SMTP); (permissions, mirroring and debounce, reply scoping, unread, events without text, membership and access loss, DM privacy, erasure).
Dev note: `scripts/dev/embedded-pg/migrate.mjs` applies new migrations to the running embedded Postgres.
