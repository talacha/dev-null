"""Builds the /dev/null OpenAPI 3.1 document from the routes, controllers, form requests and
resources of nunomaduro/dev-null.sh. Run: python3 build_spec.py <out_dir>"""

import json
import sys
from pathlib import Path

import yaml

SOURCE_COMMIT = "32315b33f52f7c2e1141a0234285f64357acd79a"
SOURCE_DATE = "2026-11-09"

# ---------------------------------------------------------------- schema helpers


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def t(type_, desc=None, null=False, **kw):
    s = {"type": [type_, "null"] if null else type_}
    if desc:
        s["description"] = desc
    s.update(kw)
    return s


def nul(schema, desc=None):
    s = {"anyOf": [schema, {"type": "null"}]}
    if desc:
        s["description"] = desc
    return s


def arr(items, desc=None, **kw):
    s = {"type": "array", "items": items}
    if desc:
        s["description"] = desc
    s.update(kw)
    return s


def obj(props, required=None, desc=None, additional=None):
    s = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    if desc:
        s["description"] = desc
    if additional is not None:
        s["additionalProperties"] = additional
    return s


UUID = t("string", format="uuid")
DATETIME = t("string", format="date-time")
DATETIME_N = t("string", format="date-time", null=True)
SIGNED_ONLY = "Only in responses to signed requests."

# ---------------------------------------------------------------- schemas

schemas = {}

schemas["Error"] = obj(
    {"message": t("string")}, ["message"],
    desc="A plain error, as Laravel renders it.")

schemas["ApiError"] = obj(
    {
        "message": t("string", "Human-readable, safe to show as is."),
        "code": ref("ApiErrorCode"),
        "user": {**ref("User"), "description": "With `user_blocked` only: the user the viewer blocked."},
    },
    ["message", "code"],
    desc="An error from the signed API. `code` never changes once released, so match on it, not on `message`.")

schemas["ApiErrorCode"] = t(
    "string",
    "| code | status | meaning |\n|---|---|---|\n"
    "| `invalid_grant` | 400 | The sign-in code expired, was already used, or doesn't match. |\n"
    "| `invalid_signature` | 401 | Missing, malformed, stale or replayed signature. |\n"
    "| `device_not_approved` | 401 | The signature is fine but nobody approved this key as a device. |\n"
    "| `user_blocked` | 403 | The viewer blocked this user (comes with `user`). |\n"
    "| `user_unavailable` | 403 | The profile isn't available to the viewer (e.g. they were blocked). |\n"
    "| `own_commit` | 403 | You can't do this to your own commit (e.g. report it). |\n"
    "| `timed_out` | 403 | The user is in a moderation timeout: they can read but not post. |\n"
    "| `banned` | 403 | The account is banned; only `DELETE /v1/me` still works. |\n"
    "| `commit_rules_required` | 403 | First-time posters must read the commit rules and post once from the web. |\n"
    "| `commit_unavailable` | 404 | The commit doesn't exist, was deleted, isn't published, or isn't visible to you. |\n"
    "| `pasteis_exhausted` | 422 | No pastéis left today. |\n"
    "| `rate_limited` | 429 | Too many requests; see `Retry-After`. |\n"
    "| `github_sync_failed` | 503 | GitHub couldn't be reached to mirror the profile. |",
    enum=["invalid_grant", "invalid_signature", "device_not_approved", "user_blocked", "user_unavailable",
          "own_commit", "timed_out", "banned", "commit_rules_required", "commit_unavailable",
          "pasteis_exhausted", "rate_limited", "github_sync_failed"])

schemas["ValidationError"] = obj(
    {
        "message": t("string", example="The body field is required."),
        "errors": obj({}, desc="Messages by field name.", additional=arr(t("string"))),
    },
    ["message", "errors"])

# Pagination ---------------------------------------------------------------

schemas["CursorLinks"] = obj(
    {
        "first": t("string", null=True, format="uri", description="Always null for cursor pages."),
        "last": t("string", null=True, format="uri", description="Always null for cursor pages."),
        "prev": t("string", null=True, format="uri"),
        "next": t("string", null=True, format="uri", description="Follow until null."),
    },
    ["first", "last", "prev", "next"])

schemas["CursorMeta"] = obj(
    {
        "path": t("string", format="uri"),
        "per_page": t("integer", example=20),
        "next_cursor": t("string", null=True, description="Pass back as `?cursor=`."),
        "prev_cursor": t("string", null=True),
    },
    ["path", "per_page", "next_cursor", "prev_cursor"])

schemas["PageLinks"] = obj(
    {k: t("string", null=True, format="uri") for k in ("first", "last", "prev", "next")})

schemas["PageMeta"] = obj(
    {
        "current_page": t("integer"),
        "from": t("integer", null=True),
        "last_page": t("integer"),
        "links": arr(obj({"url": t("string", null=True), "label": t("string"), "active": t("boolean")})),
        "path": t("string", format="uri"),
        "per_page": t("integer"),
        "to": t("integer", null=True),
        "total": t("integer"),
    })

# Bodies ---------------------------------------------------------------------

schemas["TextSegment"] = obj({"type": t("string", const="text"), "text": t("string")}, ["type", "text"], desc="Prose.")
schemas["CodeSegment"] = obj({"type": t("string", const="code"), "code": t("string")}, ["type", "code"],
                             desc="Inline `code`.")
schemas["BlockSegment"] = obj({
    "type": t("string", const="block"),
    "language": t("string", null=True),
    "filename": t("string", null=True),
    "html": t("string", "Syntax-highlighted HTML of the fenced block."),
}, ["type", "language", "html"], desc="A fenced code block.")
schemas["Segment"] = {
    "description": "A piece of a body, split for rendering: prose, inline code, or a highlighted code block.",
    "oneOf": [ref("TextSegment"), ref("CodeSegment"), ref("BlockSegment")],
    "discriminator": {"propertyName": "type", "mapping": {
        "text": "#/components/schemas/TextSegment",
        "code": "#/components/schemas/CodeSegment",
        "block": "#/components/schemas/BlockSegment",
    }},
}

schemas["Mention"] = obj(
    {
        "handle": t("string"),
        "offset": t("integer", "Character offset of the `@` in the body."),
        "length": t("integer"),
        "kind": t("string", enum=["user", "organization"]),
    },
    ["handle", "offset", "length"])

schemas["LinkPreview"] = obj(
    {
        "url": t("string", format="uri"),
        "title": t("string", null=True),
        "description": t("string", null=True),
        "image_url": t("string", null=True, format="uri"),
        "site_name": t("string", null=True),
        "is_pending": t("boolean", "True until the card has been fetched; ask again later."),
        "embed": nul(obj({
            "provider": t("string"),
            "kind": t("string"),
            "src": t("string", format="uri"),
            "aspect_ratio": t("number", null=True),
            "height": t("integer", null=True),
            "poster": t("string", null=True),
        }), "A playable embed (e.g. video) when the link supports one."),
    })

schemas["CommitImage"] = obj(
    {
        "id": UUID,
        "width": t("integer"),
        "height": t("integer"),
        "description": t("string", null=True, description="Alt text."),
        "url": t("string", format="uri", description="Signed and temporary while the commit is pending review."),
    },
    ["id", "width", "height", "url"])

schemas["Poll"] = obj(
    {
        "id": UUID,
        "closes_at": DATETIME_N,
        "is_closed": t("boolean"),
        "has_voted": t("boolean"),
        "total_votes": t("integer", null=True, description="Null until you voted, wrote the poll, or it closed."),
        "options": arr(obj({
            "id": UUID,
            "label": t("string"),
            "votes_count": t("integer", null=True),
            "voted": t("boolean"),
            "percentage": t("integer", null=True),
        })),
    })

schemas["LiveNow"] = obj(
    {
        "platform": t("string", enum=["youtube", "twitch"]),
        "url": t("string", format="uri"),
        "thumbnail_url": t("string", format="uri"),
        "ends_at": DATETIME,
    })

schemas["Lane"] = {
    "description": "The profile color: a lane index (0-5) or a custom `#rrggbb` color.",
    "oneOf": [t("integer", minimum=0, maximum=5), t("string", pattern="^#[0-9a-f]{6}$")],
}

# People ---------------------------------------------------------------------

schemas["User"] = obj(
    {
        "id": UUID,
        "handle": t("string", "GitHub login.", example="nunomaduro"),
        "name": t("string", null=True),
        "avatar_url": t("string", null=True, format="uri"),
        "bio": t("string", null=True),
        "company": t("string", null=True),
        "location": t("string", null=True),
        "website": t("string", null=True),
        "github_url": t("string", format="uri"),
        "html_url": t("string", format="uri", example="https://dev-null.sh/@nunomaduro"),
        "feed_url": t("string", format="uri", description="Atom feed of their commits."),
        "created_at": DATETIME,
        "live": nul(ref("LiveNow"), "The stream they're on right now, if any."),
        "commits_count": t("integer", "When counted (profile pages)."),
        "followers_count": t("integer", "When counted (profile pages)."),
        "following_count": t("integer", "When counted (profile pages)."),
        "lane": {**ref("Lane"), "description": SIGNED_ONLY},
        "is_followed": t("boolean", "In lists for signed requests: whether you follow them."),
        "follows_you": t("boolean", "In lists for signed requests: whether they follow you."),
        "followed_by_following_count": t("integer", "In some lists: how many people you follow follow them."),
    },
    ["id", "handle", "name", "avatar_url", "github_url", "html_url", "feed_url", "created_at"],
    desc="A developer, as their public profile shows them.")

schemas["Organization"] = obj(
    {
        "handle": t("string", example="laravel"),
        "name": t("string", null=True),
        "avatar_url": t("string", null=True, format="uri"),
        "bio": t("string", null=True),
        "location": t("string", null=True),
        "website": t("string", null=True),
        "github_url": t("string", format="uri"),
        "html_url": t("string", format="uri"),
        "lane": nul(ref("Lane"), "Chosen by its admins; null for /dev/null's blue."),
        "is_followed": t("boolean", "In lists for signed requests."),
        "followers_count": t("integer", "On its own page."),
        "admins": arr(ref("User"), "On its own page, first admin first."),
    },
    ["handle", "name", "avatar_url", "github_url", "html_url", "lane"],
    desc="A GitHub organization's page on /dev/null. Organizations share `@handle` URLs with users.")

schemas["UserProfile"] = {
    "description": "A user as a commit author or actor.",
    "allOf": [obj({"type": t("string", const="user"), "id": UUID}, ["type", "id"]), ref("User")],
}
schemas["OrganizationProfile"] = {
    "description": "An organization as a commit author or actor.",
    "allOf": [obj({"type": t("string", const="organization"), "id": UUID}, ["type", "id"]), ref("Organization")],
}
schemas["Profile"] = {
    "description": "A commit author or notification actor: a user or an organization, as `type` says, with its `id` either way.",
    "oneOf": [ref("UserProfile"), ref("OrganizationProfile")],
    "discriminator": {"propertyName": "type", "mapping": {
        "user": "#/components/schemas/UserProfile",
        "organization": "#/components/schemas/OrganizationProfile",
    }},
}

schemas["CurrentUser"] = {
    "description": "The signed-in user: their public profile plus what only they see in Settings.",
    "allOf": [
        ref("User"),
        obj({
            "pasteis_mode": t("boolean"),
            "pasteis_remaining": t("integer", "Pastéis left to give today."),
            "pasteis_resets_at": DATETIME,
            "pasteis_received": t("integer"),
            "preferred_lane": nul(ref("Lane"), "Null for Automatic."),
            "automatic_lane": ref("Lane"),
            "sponsors_url": t("string", null=True, format="uri"),
            "github_synced_at": DATETIME_N,
            "terms_version": t("string", "The version of the terms in force."),
            "terms_accepted_at": DATETIME_N,
            "terms_accepted": t("boolean", "Whether the accepted version is the current one."),
            "remotes": nul(obj({
                "from": t("string", enum=["following", "everyone"], description="Who can push to you."),
                "pull_receipts": t("boolean", "Whether you share read receipts."),
                "requests": t("boolean", "Site flag: message requests are enabled."),
                "everyone": t("boolean", "Site flag: `from: everyone` may be chosen."),
                "unread_count": t("integer"),
            }), "Null while Remotes (DMs) are turned off."),
        }),
    ],
}

schemas["UserAchievements"] = obj(
    {
        "level": t("integer"),
        "rank": t("string"),
        "xp": t("integer"),
        "next_level_xp": t("integer", null=True),
        "level_progress": t("integer"),
        "xp_breakdown": obj({}, desc="By source: commits, streak, stars_received, replies, stars_given, luddite, shell_shocked.",
                            additional=obj({"count": t("integer"), "multiplier": t("integer"), "xp": t("integer")})),
        "ranks": arr(obj({"rank": t("string"), "level": t("integer"), "min_xp": t("integer"),
                          "description": t("string"), "achieved": t("boolean")})),
        "badges": arr(obj({"id": t("string"), "name": t("string"), "description": t("string"), "icon": t("string"),
                           "unlocked": t("boolean"), "progress": t("integer"), "target": t("integer")})),
    })

schemas["Device"] = obj(
    {
        "id": UUID,
        "name": t("string", example="Rob's iPhone"),
        "app_name": t("string", null=True),
        "fingerprint": t("string", example="SHA256:2rM1n9yS1xH3V6tJ8pQe0oZf5b4cWkLmN7aDgUuYiRs"),
        "approved_at": DATETIME,
        "last_used_at": DATETIME_N,
    },
    desc="A key approved to sign requests as the user. Never includes the key itself.")

# Commits --------------------------------------------------------------------

schemas["Commit"] = obj(
    {
        "id": UUID,
        "short_hash": t("string", "Last 7 hex chars of the id, as shown on the site.", example="cc07562"),
        "body": t("string", "Markdown-ish text, up to 4,000 characters."),
        "parent_id": t("string", null=True, format="uuid",
                       description="The commit this replies to. Unsigned requests only see it when the parent is public."),
        "html_url": t("string", format="uri"),
        "created_at": DATETIME,
        "stars_count": t("integer"),
        "replies_count": t("integer"),
        "link_preview": nul(ref("LinkPreview")),
        "images": arr(ref("CommitImage"), maxItems=3),
        "author": ref("Profile"),
        "body_segments": arr(ref("Segment"), SIGNED_ONLY),
        "preview_segments": t("array", null=True, items=ref("Segment"),
                              description=SIGNED_ONLY + " The excerpt a list shows of a long commit, or null when it fits."),
        "mentions": arr(ref("Mention"), SIGNED_ONLY),
        "status": t("string", SIGNED_ONLY + " Moderation status; others only ever see approved commits.",
                    enum=["pending", "approved", "rejected"]),
        "is_pinned": t("boolean", SIGNED_ONLY),
        "starred": t("boolean", SIGNED_ONLY + " Whether you starred it."),
        "pasteis_count": t("integer", SIGNED_ONLY),
        "deleted_at": t("null", SIGNED_ONLY),
        "parent": nul(ref("CommitOrTombstone"), SIGNED_ONLY + " When loaded; null when you may not see the parent."),
        "quoted_commit_id": t("string", null=True, format="uuid", description=SIGNED_ONLY),
        "quoted_commit": nul(ref("CommitOrTombstone"), SIGNED_ONLY + " Null once you can no longer see the quoted commit; a tombstone if it was deleted."),
        "poll": nul(ref("Poll"), SIGNED_ONLY),
        "reply_preview": obj({
            "data": arr(ref("CommitOrTombstone")),
            "next_cursor": t("string", null=True),
        }, desc=SIGNED_ONLY + " In lists: the newest replies the site shows under the card."),
    },
    ["id", "short_hash", "body", "parent_id", "html_url", "created_at", "author"],
    desc="A post (\"commit\") on the log. Counts, `link_preview`, `images` and relations are only present when loaded.")

schemas["DeletedCommit"] = obj(
    {"id": UUID, "parent_id": t("string", null=True, format="uuid"), "deleted_at": DATETIME,
     "replies_count": t("integer")},
    ["id", "parent_id", "deleted_at"],
    desc="A tombstone: a deleted commit that still has replies stays in its thread without author or body. Signed requests only.")

schemas["CommitOrTombstone"] = {
    "description": "A commit, or (signed requests only) a tombstone where a deleted commit with replies stood. "
                   "Tell them apart by `deleted_at` being set, or `author` missing.",
    "anyOf": [ref("Commit"), ref("DeletedCommit")],
}

schemas["ScheduledCommit"] = obj(
    {
        "id": UUID,
        "author": nul(ref("Profile"), "The organization it goes out as, or null for yourself."),
        "body": t("string", null=True, description="Null once submitted (it lives on the commit then)."),
        "body_segments": arr(ref("Segment")),
        "preview_segments": t("array", null=True, items=ref("Segment")),
        "poll_options": t("array", null=True, items=t("string")),
        "image_count": t("integer"),
        "scheduled_at": DATETIME,
        "submitted_at": DATETIME_N,
        "status": t("string", enum=["scheduled", "pending", "approved", "rejected", "deleted"]),
    })

schemas["CommitTranslation"] = obj(
    {
        "language": t("string", example="es"),
        "source_language": t("string", null=True),
        "source_name": t("string", null=True, example="English"),
        "available": t("boolean", "Whether translating makes sense (source differs and is known)."),
        "translated": nul(obj({
            "body_segments": arr(ref("Segment")),
            "preview_segments": t("array", null=True, items=ref("Segment")),
        })),
    })

schemas["NewPoll"] = obj(
    {
        "options": arr(t("string", maxLength=50), "2-4 distinct options.", minItems=2, maxItems=4),
        "duration": t("integer", "Minutes the poll stays open.", enum=[60, 1440, 4320, 10080]),
    },
    ["options", "duration"])

# Notifications ----------------------------------------------------------------

schemas["Notification"] = obj(
    {
        "id": UUID,
        "type": t("string", enum=["followed", "replied", "mentioned", "approved", "rejected", "quoted", "starred",
                                  "leveled_up", "first_commit"]),
        "subject_id": t("string", null=True),
        "reason": t("string", null=True, description="For `rejected`: the moderator's reason."),
        "read_at": DATETIME_N,
        "created_at": DATETIME,
        "actor": ref("Profile"),
        "actors": arr(ref("Profile"), "In lists: the first few actors of the group."),
        "organization": nul(ref("Organization"), "Set when a member hears about an organization's commits or mentions."),
        "group_id": t("string", null=True),
        "event_count": t("integer", null=True),
        "actors_count": t("integer", null=True),
        "unread_count": t("integer", null=True),
        "commit": nul(ref("Commit")),
    },
    desc="A group of notifications, represented by its newest one.")

# Remotes (direct messages and group "orgs") -----------------------------------------

schemas["Reaction"] = obj({"user_id": UUID, "emoji": t("string", example="🔥")})

schemas["Message"] = obj(
    {
        "id": t("integer"),
        "user_id": t("string", null=True, format="uuid"),
        "client_id": t("string", null=True, format="uuid", description="The id the sender's client generated (idempotency key)."),
        "body": t("string", null=True),
        "body_segments": arr(ref("Segment")),
        "mentions": arr(ref("Mention")),
        "reply_to_id": t("integer", null=True),
        "reply_to": obj({"id": t("integer"), "user_id": t("string", null=True), "body": t("string", null=True),
                         "images_count": t("integer"), "has_voice": t("boolean")}),
        "link_preview": nul(ref("LinkPreview")),
        "images": arr(obj({"id": UUID, "width": t("integer"), "height": t("integer"),
                           "description": t("string", null=True),
                           "url": t("string", format="uri", description="Signed for you; see `GET /v1/remotes/images/{image}`.")})),
        "voice": nul(obj({"id": UUID, "duration_ms": t("integer"), "waveform": arr(t("integer")),
                          "url": t("string", format="uri", description="Signed for you; see `GET /v1/remotes/voices/{voice}`.")})),
        "reactions": arr(ref("Reaction")),
        "event": t("string", null=True, description="In orgs: the event this message records.",
                   enum=["created", "added", "removed", "left", "renamed", "promoted", "demoted", "inherited", "ping",
                         "call_started", "call_answered", "call_cancelled", "call_declined", "call_missed",
                         "call_failed", None]),
        "subject_id": t("string", null=True, description="In orgs: who an event is about."),
        "user": ref("User"),
        "subject": ref("User"),
        "pinned_at": DATETIME_N,
        "created_at": DATETIME,
    })

schemas["OrgRole"] = t("string", enum=["maintainer", "contributor"])
schemas["PushAccess"] = t(
    "string", "What the composer can do: `open` push freely; `request` the first message becomes a request; "
              "`waiting` your request hasn't been merged; `restricted`/`closed` you can't push.",
    enum=["open", "request", "waiting", "restricted", "closed"])

schemas["Conversation"] = obj(
    {
        "id": UUID,
        "kind": t("string", enum=["direct", "org"]),
        "name": t("string", null=True, description="Orgs only."),
        "partner": nul(ref("User"), "Direct conversations only."),
        "members": t("array", null=True, items=obj({"user": ref("User"), "role": nul(ref("OrgRole"))}),
                     description="Orgs only."),
        "last_message": nul(ref("Message")),
        "last_message_at": DATETIME_N,
        "ahead": t("integer", "Messages from others you haven't pulled (read) yet."),
        "last_incoming_message_id": t("integer", null=True),
        "last_incoming_sender": t("string", null=True),
        "partner_read_through_id": t("integer"),
        "partner_read_at": DATETIME_N,
        "is_archived": t("boolean", "Stashed."),
        "pinned_at": DATETIME_N,
        "muted_until_at": DATETIME_N,
    },
    desc="A row of the Remotes inbox.")

reaction_changes = arr(obj({"id": t("integer"), "reactions": arr(ref("Reaction"))}),
                       "Reactions changed since `reactions_after`.")

schemas["DirectThread"] = obj(
    {
        "partner": ref("User"),
        "messages": arr(ref("Message")),
        "has_older": t("boolean"),
        "reactions_version": t("integer", "Pass back as `reactions_after` when polling."),
        "reaction_changes": reaction_changes,
        "read_through_id": t("integer"),
        "partner_read_through_id": t("integer"),
        "partner_read_at": DATETIME_N,
        "partner_typing": t("boolean"),
        "is_archived": t("boolean"),
        "pinned_at": DATETIME_N,
        "muted_until_at": DATETIME_N,
        "access": ref("PushAccess"),
    })

schemas["OrgThread"] = obj(
    {
        "org": obj({"id": UUID, "name": t("string", null=True)}),
        "messages": arr(ref("Message")),
        "has_older": t("boolean"),
        "reactions_version": t("integer"),
        "reaction_changes": reaction_changes,
        "pinned": t("array", null=True, items=ref("Message"), description="Null when unchanged since `reactions_after`."),
        "mentions": arr(ref("Message"), "Messages that mention you, until you clear them."),
        "mentions_count": t("integer"),
        "read_through_id": t("integer"),
        "members": arr(obj({"role": nul(ref("OrgRole")), "read_through_id": t("integer"), "user": ref("User")})),
        "typing": arr(t("string"), "Handles of members typing now."),
        "is_archived": t("boolean"),
        "pinned_at": DATETIME_N,
        "muted_until_at": DATETIME_N,
        "role": nul(ref("OrgRole"), "Your role."),
        "access": ref("PushAccess"),
    })

schemas["CallMember"] = obj({"user": ref("User"), "joined_at": t("integer", "Unix timestamp.")})
schemas["CallSignal"] = obj({"id": t("string", maxLength=64), "type": t("string", enum=["offer", "answer"]),
                             "sdp": t("string", maxLength=10000)}, ["id", "type", "sdp"])
schemas["OrgCall"] = obj(
    {
        "started_at": t("integer", "Unix timestamp."),
        "is_ringing": t("boolean"),
        "members": arr(ref("CallMember"), maxItems=8),
        "signals": obj({}, desc="WebRTC signals addressed to you, by sender.", additional=ref("CallSignal")),
    })
schemas["IceServers"] = obj(
    {
        "ice_servers": arr(obj({"urls": arr(t("string")), "username": t("string"), "credential": t("string")}),
                           "Short-lived TURN credentials for one call."),
        "is_relay_only": t("boolean"),
    })

# Settings ------------------------------------------------------------------------

schemas["PushPreferences"] = obj(
    {k: t("boolean") for k in ("follows", "replies", "mentions", "direct_remotes", "org_remotes")},
    ["follows", "replies", "mentions", "direct_remotes", "org_remotes"])

schemas["Settings"] = obj(
    {
        "timezone": t("string", null=True, example="America/Mexico_City"),
        "show_local_time": t("boolean"),
        "translation_language": t("string", null=True, description="Null to follow the device."),
        "automatic_translation": t("boolean"),
        "translation_languages": arr(obj({"code": t("string"), "name": t("string"), "native_name": t("string")})),
        "is_admin": t("boolean"),
        "push": ref("PushPreferences"),
    })

schemas["MacAppRelease"] = obj(
    {
        "version": t("string", example="0.4.0"),
        "build": t("integer"),
        "revision": t("string"),
        "released_at": t("string"),
        "minimum_system_version": t("string", example="14.0"),
        "notarized": t("boolean"),
        "size": t("integer", "Bytes."),
        "sha256": t("string"),
        "download_url": t("string", format="uri"),
        "url": t("string", format="uri"),
    })

# ---------------------------------------------------------------- envelopes


def data_of(schema, extra=None, required_extra=None):
    props = {"data": schema}
    props.update(extra or {})
    return obj(props, ["data"] + (required_extra or []))


def cursor_page(item, extra=None):
    props = {"data": arr(item), "links": ref("CursorLinks"), "meta": ref("CursorMeta")}
    props.update(extra or {})
    return obj(props, ["data", "links", "meta"])


schemas["CommitResponse"] = data_of(ref("Commit"))
schemas["CommitPage"] = cursor_page(ref("CommitOrTombstone"))
schemas["UserPage"] = cursor_page(ref("User"))
schemas["CurrentUserResponse"] = data_of(ref("CurrentUser"), {"unread_notifications_count": t("integer")},
                                         ["unread_notifications_count"])
schemas["MessageResponse"] = data_of(ref("Message"))

# ---------------------------------------------------------------- parameters

P = {}


def path_param(name, desc, schema, example=None):
    p = {"name": name, "in": "path", "required": True, "description": desc, "schema": schema}
    if example is not None:
        p["example"] = example
    return p


def query(name, desc, schema, required=False, example=None):
    p = {"name": name, "in": "query", "required": required, "description": desc, "schema": schema}
    if example is not None:
        p["example"] = example
    return p


P["handle"] = path_param("handle", "A user's handle (their GitHub login).", t("string"), "nunomaduro")
P["orgHandle"] = path_param("handle", "An organization's handle (its GitHub login).", t("string"), "laravel")
P["commit"] = path_param("commit", "Commit id (UUID).", UUID, "01a1c63c-ae57-70cc-adf3-2298cc075627")
P["partner"] = path_param("partner", "The other person's handle, after the literal `@`.", t("string"), "nunomaduro")
P["org"] = path_param("org", "Org (group conversation) id.", UUID)
P["message"] = path_param("message", "Message id.", t("integer"))
P["member"] = path_param("member", "The member's handle.", t("string"))
P["cursor"] = query("cursor", "Opaque cursor from `meta.next_cursor` / `links.next`.", t("string"))

components_parameters = {
    "Handle": P["handle"], "OrgHandle": P["orgHandle"], "Commit": P["commit"], "Partner": P["partner"],
    "Org": P["org"], "Message": P["message"], "Member": P["member"], "Cursor": P["cursor"],
}


def pref(name):
    return {"$ref": f"#/components/parameters/{name}"}


# ---------------------------------------------------------------- responses

R = {
    "NoContent": {"description": "Done. No body."},
    "BadRequest": {"description": "Invalid grant.", "content": {"application/json": {"schema": ref("ApiError")}}},
    "Unauthorized": {"description": "`invalid_signature` or `device_not_approved`.",
                     "content": {"application/json": {"schema": ref("ApiError")}}},
    "Forbidden": {"description": "Not allowed: `banned`, `timed_out`, `user_blocked`, `user_unavailable`, `own_commit`, "
                                 "`commit_rules_required`, or a plain policy message.",
                  "content": {"application/json": {"schema": {"anyOf": [ref("ApiError"), ref("Error")]}}}},
    "NotFound": {"description": "Not found, or not visible to you (the API answers both alike).",
                 "content": {"application/json": {"schema": {"anyOf": [ref("ApiError"), ref("Error")]}}}},
    "Conflict": {"description": "The state changed underneath you; refresh.",
                 "content": {"application/json": {"schema": ref("Error")}}},
    "Unprocessable": {"description": "Validation failed.",
                      "content": {"application/json": {"schema": ref("ValidationError")}}},
    "TooManyRequests": {"description": "Rate limited.",
                        "headers": {"Retry-After": {"description": "Seconds to wait.", "schema": t("integer")}},
                        "content": {"application/json": {"schema": {"anyOf": [ref("ApiError"), ref("Error")]}}}},
    "ServiceUnavailable": {"description": "An upstream service failed; retry.",
                           "content": {"application/json": {"schema": {"anyOf": [ref("ApiError"), ref("Error")]}}}},
}


def rref(name):
    return {"$ref": f"#/components/responses/{name}"}


def ok(schema, desc="OK", status="200", headers=None):
    r = {"description": desc, "content": {"application/json": {"schema": schema}}}
    if headers:
        r["headers"] = headers
    return {status: r}


# ---------------------------------------------------------------- security

SIGNED = [{"sshSignature": [], "devnullTimestamp": [], "devnullNonce": []}]
OPTIONAL = [{}] + SIGNED
NONE = []
CLI = [{"cliSignature": []}]

RATE = {
    "api": "120/min per user when signed; 60/min per IP when not",
    "devices": "60/min per IP",
    "broadcast-authorizations": "60/min",
    "profile-syncs": "limited per user",
    "people": "120/min (shared by people search, mention suggestions and hover cards)",
    "search": "15/min (each search costs an embedding)",
    "issue-suggestions": "30/min and 300/day",
    "conversations": "300/min",
    "messages": "30/min",
    "pings": "3/min",
    "pins": "20/min",
    "stars": "60/min",
    "follows": "30/min",
    "commit-reports": "5/min",
    "commits": "10 commits/min, however they are posted",
    "translations": "10/min",
    "pasteis": "60/min",
    "claims": "10/min",
    "cli-key-lookups": "60/min per IP",
}

# ---------------------------------------------------------------- operations

paths = {}
op_ids = set()


def op(method, path, tag, op_id, summary, desc=None, auth="signed", params=None, body=None, responses=None,
       throttle=None, errors=None, deprecated=False, extra=None):
    assert op_id not in op_ids, op_id
    op_ids.add(op_id)
    security = {"signed": SIGNED, "optional": OPTIONAL, "none": NONE, "cli": CLI, "unapproved": SIGNED}[auth]
    o = {"tags": [tag], "operationId": op_id, "summary": summary}
    d = desc or ""
    if auth == "optional":
        d += ("\n\n**Auth:** public. Sign the request to get the signed-in view (extra fields marked "
              "*signed requests only*). A request with any signature header must be signed correctly.")
    elif auth == "unapproved":
        d += "\n\n**Auth:** signed with the key being approved; the key need not be approved yet."
    throttles = ["api"] if path.startswith("/v1/") and throttle != "devices" and not path.startswith("/v1/remotes/images") \
        and not path.startswith("/v1/remotes/voices") else []
    if throttle:
        throttles += throttle if isinstance(throttle, list) else [throttle]
    if throttles:
        d += "\n\n**Rate limits:** " + "; ".join(f"`{n}` {RATE[n]}" for n in dict.fromkeys(throttles)) + "."
        o["x-rate-limit"] = list(dict.fromkeys(throttles))
    o["description"] = d.strip()
    o["security"] = security
    if params:
        o["parameters"] = params
    if body:
        o["requestBody"] = body
    rs = dict(responses or {"204": rref("NoContent")})
    errs = errors
    if errs is None:
        errs = ["401", "403", "404", "422", "429"] if auth in ("signed", "unapproved") else ["404", "429"]
    names = {"400": "BadRequest", "401": "Unauthorized", "403": "Forbidden", "404": "NotFound", "409": "Conflict",
             "422": "Unprocessable", "429": "TooManyRequests", "503": "ServiceUnavailable"}
    for e in errs:
        rs.setdefault(e, rref(names[e]))
    o["responses"] = dict(sorted(rs.items()))
    if deprecated:
        o["deprecated"] = True
    if extra:
        o.update(extra)
    paths.setdefault(path, {})[method] = o


def json_body(schema, required=True, desc=None):
    b = {"required": required, "content": {"application/json": {"schema": schema}}}
    if desc:
        b["description"] = desc
    return b


def json_or_multipart(schema, file_field, file_desc, desc=None):
    """Signed requests with files: the JSON goes in a `payload` part next to the files."""
    files = {
        "images": {"images[]": arr(t("string", contentMediaType="image/*"), file_desc, maxItems=3)},
        "voice": {"voice": t("string", file_desc, contentMediaType="audio/*")},
        "images_or_voice": {
            "images[]": arr(t("string", contentMediaType="image/*"), "JPEG, PNG or WebP; up to 3; 10 MB each.", maxItems=3),
            "voice": t("string", "A voice note (0.5-61 s, under ~1.9 MB). Excludes `body` and images.",
                       contentMediaType="audio/*"),
        },
    }[file_field]
    mp = obj({"payload": t("string", "The JSON body as a file part (`application/json`).", contentMediaType="application/json"),
              **files}, ["payload"])
    return {
        "required": True,
        "description": (desc or "") + "\n\nSend JSON, or `multipart/form-data` when attaching files. With files, the "
                                      "signature uses the `devnull-api-images` namespace and covers their SHA-256 "
                                      "hashes (see *Requests with files*).",
        "content": {
            "application/json": {"schema": schema},
            "multipart/form-data": {"schema": mp, "encoding": {"payload": {"contentType": "application/json"}}},
        },
    }


# ---- Users (public reads) -------------------------------------------------------

user_signed_extra = {
    "bio_profiles": obj({}, desc="Handles the bio/company mention that have a page on /dev/null, by lowercase handle.",
                        additional=t("string")),
    "is_following": t("boolean", SIGNED_ONLY),
    "follows_you": t("boolean", SIGNED_ONLY),
    "is_muting": t("boolean", SIGNED_ONLY),
    "pasteis_received": t("integer", SIGNED_ONLY),
    "activity": obj({"scale": t("string", enum=["day", "week", "month", "year"]),
                     "buckets": arr(obj({"date": t("string"), "count": t("integer")}))}, desc=SIGNED_ONLY),
    "streaks": obj({"longest": t("integer"), "current": t("integer")}, desc=SIGNED_ONLY),
    "achievements": {**ref("UserAchievements"), "description": SIGNED_ONLY},
    "pinned_commit": nul(ref("Commit"), SIGNED_ONLY + " The pinned commit is left out of the commits list."),
}

op("get", "/v1/users/{handle}", "Users", "getUser", "Get a user's profile",
   "A developer's profile with follower/following/commit counts. Signed requests also get their activity graph, "
   "streaks, achievements, pinned commit, and your relationship to them.",
   auth="optional", params=[pref("Handle")],
   responses=ok(data_of(ref("User"), user_signed_extra, ["bio_profiles"])),
   errors=["403", "404", "429"])

op("get", "/v1/users/{handle}/commits", "Users", "listUserCommits", "List a user's commits",
   "The profile's Commits tab, or its Replies tab with `replies=1`. Newest first, 20 per page.",
   auth="optional",
   params=[pref("Handle"), query("replies", "Replies tab instead of top-level commits.", t("boolean")), pref("Cursor")],
   responses=ok(ref("CommitPage")), errors=["403", "404", "429"])

op("get", "/v1/users/{handle}/followers", "Users", "listUserFollowers", "List a user's followers",
   "30 per page, with `is_followed` / `follows_you` for each. Members only, so scrapers can't walk the graph.",
   params=[pref("Handle"), pref("Cursor")], responses=ok(ref("UserPage")))

op("get", "/v1/users/{handle}/following", "Users", "listUserFollowing", "List who a user follows",
   "30 per page, with `is_followed` / `follows_you` for each.",
   params=[pref("Handle"), pref("Cursor")], responses=ok(ref("UserPage")))

op("get", "/v1/users/{handle}/following/organizations", "Users", "listUserFollowedOrganizations",
   "List organizations a user follows", "30 per page, newest follow first, with `is_followed` for each.",
   params=[pref("Handle"), pref("Cursor")], responses=ok(cursor_page(ref("Organization"))))

op("post", "/v1/users/{handle}/follow", "Users", "followUser", "Follow a user", params=[pref("Handle")], throttle="follows")
op("delete", "/v1/users/{handle}/follow", "Users", "unfollowUser", "Unfollow a user", params=[pref("Handle")], throttle="follows")

op("post", "/v1/users/{handle}/mute", "Users", "muteUser", "Mute a user", "Silent: they aren't told.",
   params=[pref("Handle")], responses=ok(data_of(ref("User"), {"is_muting": t("boolean", const=True)})))
op("delete", "/v1/users/{handle}/mute", "Users", "unmuteUser", "Unmute a user",
   params=[pref("Handle")], responses=ok(data_of(ref("User"), {"is_muting": t("boolean", const=False)})))
op("post", "/v1/users/{handle}/block", "Users", "blockUser", "Block a user",
   "Ends follows both ways. Neither of you can follow, reply to, star, or see the other's commits.",
   params=[pref("Handle")], responses=ok(data_of(ref("User"), {"is_blocking": t("boolean", const=True)})))
op("delete", "/v1/users/{handle}/block", "Users", "unblockUser", "Unblock a user", "Follows don't come back.",
   params=[pref("Handle")], responses=ok(data_of(ref("User"), {"is_blocking": t("boolean", const=False)})))
op("post", "/v1/users/{handle}/dismiss", "Users", "dismissSuggestedUser", "Dismiss a follow suggestion",
   "\"Not interested\": they're never suggested again.", params=[pref("Handle")])

# ---- Organizations --------------------------------------------------------------

op("get", "/v1/organizations/{handle}", "Organizations", "getOrganization", "Get an organization's page",
   "Organizations share `@handle` URLs with users; ask here when no user has the handle.",
   auth="optional", params=[pref("OrgHandle")],
   responses=ok(data_of(ref("Organization"), {
       "is_following": t("boolean"),
       "can_claim": t("boolean", "Signed-in users can claim a page until it has an admin."),
       "settings_url": t("string", null=True, format="uri", description="For its admins and members."),
   }, ["is_following", "can_claim", "settings_url"])))

op("get", "/v1/organizations/{handle}/commits", "Organizations", "listOrganizationCommits",
   "List commits posted as an organization", "Top-level, approved, newest first, 20 per page.",
   auth="optional", params=[pref("OrgHandle"), pref("Cursor")], responses=ok(ref("CommitPage")))

op("get", "/v1/organizations/{handle}/mentions", "Organizations", "listOrganizationMentions",
   "List commits mentioning an organization", "Newest first, 20 per page.",
   auth="optional", params=[pref("OrgHandle"), pref("Cursor")], responses=ok(ref("CommitPage")))

op("post", "/v1/organizations/{handle}/follow", "Organizations", "followOrganization", "Follow an organization",
   params=[pref("OrgHandle")], throttle="follows")
op("delete", "/v1/organizations/{handle}/follow", "Organizations", "unfollowOrganization", "Unfollow an organization",
   params=[pref("OrgHandle")], throttle="follows")
op("post", "/v1/organizations/{handle}/claim", "Organizations", "claimOrganization", "Claim an organization's page",
   "Become its admin; GitHub must confirm you belong to the organization.",
   params=[pref("OrgHandle")], throttle="claims", errors=["401", "403", "404", "409", "429"])

# ---- Commits --------------------------------------------------------------------

op("get", "/v1/commits/{commit}", "Commits", "getCommit", "Get a commit",
   "Signed requests get the commit as its page shows it to you, with the thread above it (`ancestors`) and who else "
   "a reply can go to (`reply_participants`).",
   auth="optional", params=[pref("Commit")],
   responses=ok(data_of(ref("Commit"), {
       "ancestors": arr(ref("CommitOrTombstone"), SIGNED_ONLY + " Oldest first."),
       "reply_participants": arr(obj({"id": UUID, "handle": t("string")}), SIGNED_ONLY),
   })))

op("get", "/v1/commits/{commit}/related", "Commits", "listRelatedCommits", "List related commits",
   "Commits nearest in meaning, by vector similarity and a relevance check.",
   auth="optional", params=[pref("Commit")], responses=ok(data_of(arr(ref("Commit")))))

commit_create = obj(
    {
        "body": t("string", "1-4,000 characters (links count as their display length; each link ≤ 2,048). "
                            "Optional when images are attached.", maxLength=40000),
        "author": t("string", null=True, description="An organization's handle to post as (you must be allowed to)."),
        "parent_id": t("string", null=True, format="uuid", description="Reply to this commit."),
        "reply_recipients": arr(t("string"), "Handles the parent was addressed to that this reply also goes to.", maxItems=100),
        "quoted_commit_id": t("string", null=True, format="uuid", description="Quote this commit. Excludes `parent_id` and `poll`."),
        "poll": nul(ref("NewPoll"), "Excludes `parent_id`, `quoted_commit_id` and images."),
        "image_descriptions": arr(t("string", null=True, maxLength=1000), "Alt text, in the order of `images[]`.", maxItems=3),
    },
    desc="The commit. In multipart requests this object is the `payload` part.")

op("post", "/v1/commits", "Commits", "createCommit", "Post a commit",
   "Posts a commit (or a reply, or a quote). It's pending review unless you're an admin. First-time posters must "
   "commit once from the web (`commit_rules_required`).",
   body=json_or_multipart(commit_create, "images", "JPEG, PNG or WebP; up to 3; 10 MB and 6000×6000 px each."),
   responses=ok(ref("CommitResponse"), "Created.", "201"), throttle="commits")

op("post", "/v1/commits/preview", "Commits", "previewCommit", "Preview a draft",
   "Renders a draft as the commit it would become (emoji shortcodes replaced, segments, excerpt, mentions). "
   "Nothing is kept and it doesn't count toward the commit rate limit.",
   body=json_body(obj({"body": t("string", maxLength=40000)}, ["body"])),
   responses=ok(data_of(obj({"body": t("string"), "body_segments": arr(ref("Segment")),
                             "preview_segments": t("array", null=True, items=ref("Segment")),
                             "mentions": arr(ref("Mention"))}))))

op("delete", "/v1/commits/{commit}", "Commits", "deleteCommit", "Delete your commit",
   "Can be undone for 30 seconds with `POST /v1/commits/{commit}/restoration`.", params=[pref("Commit")])

op("post", "/v1/commits/{commit}/restoration", "Commits", "restoreCommit", "Undo a deletion",
   "Within the 30-second undo window.", params=[pref("Commit")], responses=ok(ref("CommitResponse")))

op("get", "/v1/commits/{commit}/replies", "Commits", "listCommitReplies", "List replies",
   "Works on deleted commits too, so a tombstone's thread can still be read.",
   params=[pref("Commit"), query("newest", "Newest first instead of oldest first.", t("boolean")), pref("Cursor")],
   responses=ok(ref("CommitPage")))

op("post", "/v1/commits/{commit}/star", "Commits", "starCommit", "Star a commit",
   params=[pref("Commit")], responses=ok(ref("CommitResponse")), throttle="stars")
op("delete", "/v1/commits/{commit}/star", "Commits", "unstarCommit", "Unstar a commit",
   params=[pref("Commit")], responses=ok(ref("CommitResponse")), throttle="stars")
op("get", "/v1/commits/{commit}/stars", "Commits", "listCommitStargazers", "List who starred a commit",
   "Newest first, 20 per page. People across a block are left out.",
   params=[pref("Commit"), pref("Cursor")], responses=ok(ref("UserPage")))

op("put", "/v1/commits/{commit}/pin", "Commits", "pinCommit", "Pin your commit to your profile",
   "Replaces the commit pinned before.", params=[pref("Commit")], responses=ok(ref("CommitResponse")), throttle="pins")
op("delete", "/v1/commits/{commit}/pin", "Commits", "unpinCommit", "Unpin your commit",
   params=[pref("Commit")], responses=ok(ref("CommitResponse")), throttle="pins")

op("post", "/v1/commits/{commit}/translation", "Commits", "translateCommit", "Translate a commit",
   params=[pref("Commit")],
   body=json_body(obj({"language": t("string", "One of `GET /v1/me/settings` → `translation_languages[].code`.", example="es")},
                      ["language"])),
   responses=ok(obj({"translation": nul(ref("CommitTranslation"))})),
   throttle="translations", errors=["401", "403", "404", "422", "429", "503"])

op("post", "/v1/commits/{commit}/reports", "Commits", "reportCommit", "Report a commit",
   "Reports are private. Reporting the same commit again keeps the first report.",
   params=[pref("Commit")],
   body=json_or_multipart(obj({
       "reason": t("string", enum=["spam", "harassment", "unsafe", "other"]),
       "details": t("string", null=True, maxLength=500),
       "image_descriptions": arr(t("string", null=True, maxLength=1000), maxItems=3),
   }, ["reason"]), "images", "Screenshots: JPEG, PNG or WebP; up to 3."),
   throttle="commit-reports")

op("post", "/v1/commits/{commit}/pasteis", "Commits", "givePastel", "Give a pastel",
   "Gives one pastel from your daily allowance. With none left: `pasteis_exhausted` (422).",
   params=[pref("Commit")],
   responses=ok(data_of(ref("Commit"), {"pasteis_remaining": t("integer"), "pasteis_resets_at": DATETIME,
                                        "author_pasteis_received": t("integer", null=True)})),
   throttle="pasteis")

op("post", "/v1/commits/{commit}/poll/votes", "Commits", "voteOnPoll", "Vote on a poll",
   "Results show once you've voted.", params=[pref("Commit")],
   body=json_body(obj({"option": t("string", "A `poll.options[].id`.", format="uuid")}, ["option"])),
   responses=ok(ref("CommitResponse")))

op("get", "/v1/starred", "Commits", "listStarredCommits", "List your starred commits", "Private to you. 20 per page.",
   params=[pref("Cursor")], responses=ok(ref("CommitPage")))

# ---- Log ------------------------------------------------------------------------

op("get", "/v1/log/{log}", "Log", "getLog", "Read the log (feed)",
   "Following, Latest or Trending, 20 commits per page. With `since`, also counts commits newer than that one "
   "(`new_commits_count`; never on Trending, which is ranked). An empty Following log comes with `suggestions`.",
   params=[path_param("log", "Which log.", t("string", enum=["following", "latest", "trending"]), "latest"),
           pref("Cursor"),
           query("since", "Id of the newest commit you already have.", UUID)],
   responses=ok(cursor_page(ref("CommitOrTombstone"), {
       "log": t("string", enum=["following", "latest", "trending"]),
       "is_ranked": t("boolean", "True for Trending."),
       "new_commits_count": t("integer", "With `since` only."),
       "suggestions": arr(ref("Commit")),
   })))

# ---- Scheduled commits ----------------------------------------------------------------

op("get", "/v1/scheduled-commits", "Scheduled commits", "listScheduledCommits", "List your scheduled commits",
   "20 per page (page-numbered, not cursor).",
   params=[query("page", "Page number.", t("integer", minimum=1))],
   responses=ok(obj({"data": arr(ref("ScheduledCommit")), "links": ref("PageLinks"), "meta": ref("PageMeta")},
                    ["data", "links", "meta"])))

op("post", "/v1/scheduled-commits", "Scheduled commits", "scheduleCommit", "Schedule a commit",
   "Only you see it until it's submitted. Can't reply to or quote a commit.",
   body=json_or_multipart(obj({
       "body": t("string", maxLength=40000),
       "author": t("string", null=True, description="Organization handle to post as."),
       "scheduled_at": t("string", "ISO 8601 with offset, in the future, at most 30 days ahead.",
                         format="date-time", example="2026-11-12T09:00:00-06:00"),
       "link_preview_url": t("string", null=True, description="One of the URLs in `body`, to show as the card."),
       "poll": nul(ref("NewPoll")),
       "image_descriptions": arr(t("string", null=True, maxLength=1000), maxItems=3),
   }, ["scheduled_at"]), "images", "JPEG, PNG or WebP; up to 3."),
   responses=ok(data_of(ref("ScheduledCommit")), "Created.", "201"), throttle="commits")

op("delete", "/v1/scheduled-commits/{scheduledCommit}", "Scheduled commits", "cancelScheduledCommit",
   "Cancel a scheduled commit", "409 when it was already submitted or canceled.",
   params=[path_param("scheduledCommit", "Scheduled commit id.", UUID)],
   errors=["401", "403", "404", "409", "429"])

op("post", "/v1/scheduled-commits/{scheduledCommit}/submission", "Scheduled commits", "submitScheduledCommit",
   "Post a scheduled commit now", "Goes through the usual review. 409 when already submitted or canceled.",
   params=[path_param("scheduledCommit", "Scheduled commit id.", UUID)],
   responses=ok(data_of(ref("ScheduledCommit"))), throttle="commits",
   errors=["401", "403", "404", "409", "429"])

# ---- Search -------------------------------------------------------------------------

op("get", "/v1/search/profiles", "Search", "searchProfiles", "Search people and organizations",
   "By name or handle. People you muted or blocked (or who blocked you) are left out; organizations only if they "
   "already have a page.",
   params=[query("q", "Search term.", t("string", maxLength=100), example="nuno")],
   responses=ok(obj({"users": arr(ref("User")), "organizations": arr(ref("Organization"))})), throttle="people")

op("get", "/v1/search/users", "Search", "searchUsers", "Search people (deprecated)",
   "Use `GET /v1/search/profiles`. Responds with `Deprecation: true` and a `Link: rel=\"successor-version\"` header.",
   params=[query("q", "Search term.", t("string", maxLength=100))],
   responses=ok(data_of(arr(ref("User")))), throttle="people", deprecated=True)

op("get", "/v1/search/commits", "Search", "searchCommits", "Search commits by meaning",
   "Semantic search, closest first; may return fewer than `limit` once irrelevant results are dropped.",
   params=[query("q", "What to look for.", t("string", minLength=3, maxLength=100), True, "cursor pagination"),
           query("limit", "Max results.", t("integer", minimum=1, maximum=100))],
   responses=ok(data_of(arr(ref("Commit")))), throttle="search")

op("get", "/v1/search/mentions", "Search", "suggestMentions", "Suggest @mentions",
   "People (and, outside orgs, organizations) the composer suggests for an @mention.",
   params=[query("q", "What was typed after `@`.", t("string", maxLength=100)),
           query("org", "Composing in this org (excludes `reply`/`quote`).", UUID),
           query("reply", "Composing a reply to this commit.", UUID),
           query("quote", "Composing a quote of this commit.", UUID)],
   responses=ok(data_of(arr(ref("User")), {"organizations": arr(ref("Organization"))})), throttle="people")

op("get", "/v1/search/issues", "Search", "suggestIssue", "Look up a /dev/null GitHub issue",
   "For `#123` references in the composer.",
   params=[query("q", "Issue number.", t("string", pattern="^[1-9][0-9]{0,9}$"), True, "42")],
   responses=ok(obj({"issue": nul(obj({"number": t("integer"), "title": t("string"), "url": t("string", format="uri")}))})),
   throttle="issue-suggestions")

# ---- Me ---------------------------------------------------------------------------

ME = rref  # noqa
cu = ok(ref("CurrentUserResponse"))

op("get", "/v1/me", "Me", "getCurrentUser", "Get the signed-in user",
   "Your profile plus private settings and the Notifications unread count.", responses=cu)
op("delete", "/v1/me", "Me", "deleteAccount", "Delete your account",
   "Deletes the account the way the web does, with its devices, so the signing key stops working. Banned users can "
   "still do this.")
op("put", "/v1/me/github", "Me", "syncFromGitHub", "Sync profile from GitHub",
   "Mirrors your GitHub profile again. `github_sync_failed` (503) when GitHub can't be reached.",
   responses=cu, throttle="profile-syncs", errors=["401", "403", "429", "503"])
op("put", "/v1/me/lane", "Me", "updateLane", "Set your profile color",
   body=json_body(obj({"lane": t("integer", null=True, minimum=0, maximum=5, description="Null for Automatic. Required (may be null)."),
                       "color": t("string", null=True, pattern="^#[0-9a-f]{6}$", description="Custom color; excludes `lane`.")},
                      ["lane"])), responses=cu)
op("put", "/v1/me/pasteis-mode", "Me", "updatePasteisMode", "Turn pastéis mode on or off",
   body=json_body(obj({"enabled": t("boolean")}, ["enabled"])), responses=cu)
op("put", "/v1/me/terms", "Me", "acceptTerms", "Accept the terms",
   "Send the version you showed the person; only the current version is accepted.",
   body=json_body(obj({"version": t("string", "Must equal `terms_version` from `GET /v1/me`.")}, ["version"])), responses=cu)
op("put", "/v1/me/live", "Me", "goLive", "Go live",
   "Marks you live on a YouTube or Twitch stream for 1-12 hours.",
   body=json_body(obj({"url": t("string", "A YouTube or Twitch stream URL.", format="uri", maxLength=2048),
                       "hours": t("integer", minimum=1, maximum=12)}, ["url", "hours"])), responses=cu)
op("delete", "/v1/me/live", "Me", "endLive", "End your stream early", responses=cu, errors=["401", "403", "429"])
op("get", "/v1/me/live-following", "Me", "listLiveFollowing", "Who you follow that's live now",
   responses=ok(data_of(arr(ref("User")))))
op("get", "/v1/me/suggested-users", "Me", "listSuggestedUsers", "Who to follow",
   "Three suggestions plus three spares. Each `round` is the next page of the day's picks. Pass `handle` or "
   "`commit_id` for suggestions shown beside a profile or commit.",
   params=[query("round", "0, 1, 2… for refreshes.", t("integer", minimum=0)),
           query("handle", "Suggest beside this profile.", t("string")),
           query("commit_id", "Suggest beside this commit (excludes `handle`).", UUID)],
   responses=ok(data_of(arr(ref("User")))))
op("get", "/v1/me/muted", "Me", "listMutedUsers", "List muted users", "Last muted first, 20 per page.",
   params=[pref("Cursor")], responses=ok(ref("UserPage")))
op("get", "/v1/me/blocked", "Me", "listBlockedUsers", "List blocked users", "Last blocked first, 20 per page.",
   params=[pref("Cursor")], responses=ok(ref("UserPage")))
op("post", "/v1/broadcasting/auth", "Me", "authorizeBroadcast", "Authorize a live-updates channel",
   "Joins your private WebSocket channel (Pusher protocol), signed like any other request.",
   body=json_body(obj({"socket_id": t("string", pattern=r"^\d+\.\d+$", example="123456.7890123"),
                       "channel_name": t("string", maxLength=200)}, ["socket_id", "channel_name"])),
   responses=ok(obj({"auth": t("string")})), throttle="broadcast-authorizations")

# ---- Settings --------------------------------------------------------------------

op("get", "/v1/me/settings", "Settings", "getSettings", "Get your settings",
   responses=ok(data_of(ref("Settings"))), errors=["401", "403", "429"])
op("put", "/v1/me/timezone", "Settings", "updateTimezone", "Set your timezone",
   body=json_body(obj({"timezone": t("string", null=True, description="IANA name, or null. Required (may be null).",
                                     example="America/Mexico_City"),
                       "show_local_time": t("boolean", null=True)}, ["timezone"])), responses=cu)
op("put", "/v1/me/automatic-translation", "Settings", "updateAutomaticTranslation", "Turn automatic translation on or off",
   body=json_body(obj({"enabled": t("boolean")}, ["enabled"])), responses=cu)
op("put", "/v1/me/translation-language", "Settings", "updateTranslationLanguage", "Set the translation language",
   body=json_body(obj({"translation_language": t("string", null=True, description="A supported code, or null to follow the device. Required (may be null).")},
                      ["translation_language"])), responses=cu)
op("put", "/v1/me/push-preferences", "Settings", "updatePushPreferences", "Choose what gets pushed to your phones",
   body=json_body(ref("PushPreferences")), responses=ok(data_of(ref("PushPreferences"))))
op("put", "/v1/me/remotes", "Settings", "updateRemotesEnabled", "Turn Remotes (DMs) on or off",
   "While off, nobody can message you and conversations wait for you to come back.",
   body=json_body(obj({"enabled": t("boolean")}, ["enabled"])), responses=cu)
op("put", "/v1/me/remote-preferences", "Settings", "updateRemotePreferences", "Set who can message you",
   body=json_body(obj({"from": t("string", "`everyone` only when the site allows it (`remotes.everyone`).",
                                 enum=["following", "everyone"]),
                       "pull_receipts": t("boolean", "Share read receipts.")}, ["from", "pull_receipts"])),
   responses=cu, throttle="conversations")

# ---- Devices & sign-in --------------------------------------------------------------

op("post", "/v1/devices", "Devices", "redeemDeviceCode", "Redeem a sign-in code for a device",
   "Step 3 of *Signing in*. Approves the key that signed this request as a device for the user who approved the app "
   "on the web, and answers like `GET /v1/me`. Any problem with the code is the same `invalid_grant` (400).",
   auth="unapproved",
   body=json_body(obj({"code": t("string", "The `code` the web redirected back with.", maxLength=255),
                       "code_verifier": t("string", "PKCE verifier (43-128 chars of `A-Z a-z 0-9 . _ ~ -`).",
                                          pattern="^[A-Za-z0-9._~-]{43,128}$"),
                       "terms_accepted": t("boolean", "Also record acceptance of the current terms.")},
                      ["code", "code_verifier"])),
   responses=cu, throttle="devices", errors=["400", "401", "422", "429"])
op("get", "/v1/me/devices", "Devices", "listDevices", "List your devices", "Newest approval first.",
   responses=ok(data_of(arr(ref("Device")))), errors=["401", "403", "429"])
op("delete", "/v1/me/devices/{device}", "Devices", "revokeDevice", "Revoke a device",
   "Revoking the device that signed this request signs the app out on it.",
   params=[path_param("device", "Device id.", UUID)])
op("put", "/v1/me/push-token", "Devices", "updatePushToken", "Register this device's push token",
   "For the device that signs the request; replaces its previous token.",
   body=json_body(obj({"token": t("string", maxLength=4096), "platform": t("string", enum=["ios", "android"])},
                      ["token", "platform"])))
op("delete", "/v1/me/push-token", "Devices", "deletePushToken", "Stop pushing to this device",
   errors=["401", "403", "429"])
op("post", "/v1/me/web-session", "Devices", "createWebSession", "Create a web session for an in-app web view",
   "Signs in the web session whose cookies this response sets, for the app's web view.",
   responses=ok(obj({"onboarded": t("boolean")}), headers={"Set-Cookie": {"schema": t("string")}}),
   errors=["401", "403", "429"])

# ---- Notifications ----------------------------------------------------------------------

ntype = query("type", "`all`, `none`, or a comma list of `replies`, `quotes`, `stars`, `mentions`, `follows`, `moderation`. "
                      "Remembered for next time.",
              t("string", pattern=r"^(?:all|none|(?:replies|quotes|stars|mentions|follows|moderation)"
                                  r"(?:,(?:replies|quotes|stars|mentions|follows|moderation))*)$"), example="replies,mentions")

op("get", "/v1/notifications", "Notifications", "listNotifications", "List notifications",
   "Grouped as on the web. **Listing marks every notification as read**, whatever the filter; `read_at` says when, "
   "so the ones read since your last `read_at` are the new ones.",
   params=[ntype, query("through", "Page through notifications up to this time.", DATETIME), pref("Cursor")],
   responses=ok(cursor_page(ref("Notification"), {"filters": obj({"type": t("string")}), "read_at": DATETIME})))
op("get", "/v1/notifications/{notification}/group", "Notifications", "listNotificationGroup",
   "Expand a notification group", "Every notification in the group, newest first, 20 per page. Marks nothing as read.",
   params=[path_param("notification", "Any notification id in the group.", UUID), ntype, pref("Cursor")],
   responses=ok(cursor_page(ref("Notification"))))

# ---- Remotes: inbox & direct conversations ------------------------------------------------

op("get", "/v1/remotes", "Remotes", "listConversations", "List conversations (inbox)",
   "Pinned first, then newest. Page with `before`.",
   params=[query("tab", "`fetched` (message requests) only when the site enables requests.",
                 t("string", enum=["open", "fetched", "stashed"])),
           query("q", "Filter by name or handle.", t("string", maxLength=100)),
           query("before", "Continue after this conversation id.", UUID)],
   responses=ok(data_of(arr(ref("Conversation")), {"has_more": t("boolean"), "unread_count": t("integer"),
                                                    "requests_count": t("integer")})),
   throttle="conversations")
op("get", "/v1/remotes/candidates", "Remotes", "listRemoteCandidates", "Find people to message or add",
   "Each candidate comes with the `reason` they can't be picked, if any.",
   params=[query("q", "Search term.", t("string", maxLength=100)),
           query("org", "Adding to this org.", UUID),
           query("for", "Which picker.", t("string", enum=["remote", "org", "share"]))],
   responses=ok(obj({"candidates": arr(obj({"user": ref("User"), "reason": t("string", null=True)}))})),
   throttle="conversations")

thread_params = [
    query("after", "Poll: only messages after this id.", t("integer", minimum=0)),
    query("before", "Load the page before this message id.", t("integer", minimum=1)),
    query("reactions_after", "Poll: reaction changes since this `reactions_version`.", t("integer", minimum=0)),
]

message_create = obj(
    {
        "body": t("string", null=True, maxLength=2000, description="Required unless images or a voice note are attached."),
        "client_id": t("string", "A UUID you generate. Resending the same one returns the existing message (200).", format="uuid"),
        "reply_to_id": t("integer", null=True),
        "link_preview_url": t("string", null=True, description="One of the URLs in `body`."),
        "image_descriptions": arr(t("string", null=True, maxLength=1000), maxItems=3),
        "voice_waveform": arr(t("integer", minimum=0, maximum=100), "Required with `voice`: exactly 48 bars.",
                              minItems=48, maxItems=48),
    },
    ["client_id"], desc="The message. In multipart requests this object is the `payload` part.")

msg_created = {
    "200": {"description": "Retry with a known `client_id`: the existing message.",
            "content": {"application/json": {"schema": ref("MessageResponse")}}},
    "201": {"description": "Created.", "content": {"application/json": {"schema": ref("MessageResponse")}}},
}

op("get", "/v1/remotes/@{partner}/messages", "Remotes", "getDirectThread", "Read a conversation",
   "The latest page, the page before a message, or everything after one plus reaction changes (polling). "
   "Someone you haven't talked to yet has an empty thread whose `access` says whether you can write first.",
   params=[pref("Partner")] + thread_params, responses=ok(data_of(ref("DirectThread"))), throttle="conversations")
op("post", "/v1/remotes/@{partner}/messages", "Remotes", "sendDirectMessage", "Send a message",
   "Starts the conversation if it's the first message.", params=[pref("Partner")],
   body=json_or_multipart(message_create, "images_or_voice", ""), responses=msg_created, throttle="messages")
op("put", "/v1/remotes/@{partner}/read", "Remotes", "markDirectRead", "Mark read through a message",
   "Only moves forward.", params=[pref("Partner")],
   body=json_body(obj({"through": t("integer", "Message id.", minimum=0)}, ["through"])), throttle="conversations")
op("put", "/v1/remotes/@{partner}/typing", "Remotes", "sendDirectTyping", "Say you're typing",
   "Lasts a few seconds; send every few seconds while composing.", params=[pref("Partner")], throttle="conversations")
op("post", "/v1/remotes/@{partner}/ping", "Remotes", "pingPartner", "Ping (nudge) the partner",
   "Only in a conversation that has started.", params=[pref("Partner")],
   responses=ok(ref("MessageResponse"), "Created.", "201"), throttle="pings")
op("post", "/v1/remotes/@{partner}/archive", "Remotes", "stashConversation", "Stash a conversation",
   "For you only; it pops back into Open when either of you writes.", params=[pref("Partner")], throttle="conversations")
op("delete", "/v1/remotes/@{partner}/archive", "Remotes", "unstashConversation", "Unstash a conversation",
   params=[pref("Partner")], throttle="conversations")
op("put", "/v1/remotes/@{partner}/mute", "Remotes", "muteConversation", "Mute or unmute a conversation",
   params=[pref("Partner")],
   body=json_body(obj({"duration": t("string", "`off` unmutes.", enum=["hour", "tomorrow", "week", "forever", "off"])},
                      ["duration"])),
   responses=ok(obj({"muted_until_at": DATETIME_N})), throttle="conversations")
op("put", "/v1/remotes/@{partner}/pin", "Remotes", "pinConversation", "Pin or unpin a conversation",
   params=[pref("Partner")], body=json_body(obj({"pinned": t("boolean")}, ["pinned"])),
   responses=ok(obj({"pinned_at": DATETIME_N})), throttle="conversations")
op("post", "/v1/remotes/@{partner}/merge", "Remotes", "acceptRequest", "Accept a message request",
   "Merges a fetched request into your open conversations so you can reply.", params=[pref("Partner")],
   throttle="conversations")
op("post", "/v1/remotes/@{partner}/drop", "Remotes", "dropRequest", "Drop a message request",
   "Drops it for good without telling the sender.", params=[pref("Partner")], throttle="conversations")

# ---- Remotes: messages ---------------------------------------------------------------------

op("get", "/v1/remotes/messages/{message}/link-preview", "Remotes", "getMessageLinkPreview", "Get a message's link card",
   "Ask again while `is_pending` is true.", params=[pref("Message")],
   responses=ok(obj({"link_preview": nul(ref("LinkPreview"))})), throttle="conversations")
op("get", "/v1/remotes/reactions", "Remotes", "listReactionUsage", "Your most-used reaction emoji",
   responses=ok(obj({"usage": arr(obj({"emoji": t("string"), "count": t("integer")}))})), throttle="conversations")
op("post", "/v1/remotes/messages/{message}/reactions", "Remotes", "addReaction", "React to a message",
   "Idempotent per emoji. Events can't be reacted to.", params=[pref("Message")],
   body=json_body(obj({"emoji": t("string", "A supported emoji.", example="🔥")}, ["emoji"])),
   responses=ok(obj({"reactions": arr(ref("Reaction"))})), throttle="conversations")
op("delete", "/v1/remotes/messages/{message}/reactions", "Remotes", "removeReaction", "Remove a reaction",
   params=[pref("Message")], body=json_body(obj({"emoji": t("string", maxLength=32)}, ["emoji"])),
   responses=ok(obj({"reactions": arr(ref("Reaction"))})), throttle="conversations")
op("put", "/v1/remotes/messages/{message}/pin", "Remotes", "pinMessage", "Pin a message in an org",
   "Maintainers only. Answers with the org's pinned messages.", params=[pref("Message")],
   responses=ok(obj({"pinned": arr(ref("Message")), "reactions_version": t("integer")})), throttle="pins")
op("delete", "/v1/remotes/messages/{message}/pin", "Remotes", "unpinMessage", "Unpin a message in an org",
   params=[pref("Message")],
   responses=ok(obj({"pinned": arr(ref("Message")), "reactions_version": t("integer")})), throttle="pins")

signed_media = [query("expires", "Unix timestamp the URL expires at.", t("integer"), True),
                query("user", "The user the URL was signed for.", UUID, True),
                query("signature", "URL signature.", t("string"), True)]
op("get", "/v1/remotes/images/{image}", "Remotes", "getMessageImage", "Download a message image",
   "Use the `url` from a message as is. Signed for you and valid until midnight UTC two days out, so it can be cached.",
   auth="none", params=[path_param("image", "Message image id.", UUID)] + signed_media,
   responses={"200": {"description": "The image.", "content": {"image/webp": {"schema": t("string", contentMediaType="image/webp")}}},
              "403": {"description": "Invalid or expired signature."}}, errors=["404"])
op("get", "/v1/remotes/voices/{voice}", "Remotes", "getMessageVoice", "Download a voice note",
   "Use the `url` from a message as is.",
   auth="none", params=[path_param("voice", "Voice note id.", UUID)] + signed_media,
   responses={"200": {"description": "The audio (WebM/Opus or WAV).",
                      "content": {"audio/*": {"schema": t("string", contentMediaType="audio/*")}}},
              "403": {"description": "Invalid or expired signature."}}, errors=["404"])

# ---- Orgs (group conversations) ---------------------------------------------------------------

op("post", "/v1/remotes/orgs", "Orgs", "createOrg", "Start an org",
   "You become its maintainer; everyone you add contributes. Up to 100 members.",
   body=json_body(obj({"name": t("string", null=True, maxLength=60),
                       "members": arr(t("string"), "Handles of /dev/null users.", minItems=1, maxItems=99)},
                      ["members"])),
   responses=ok(obj({"org": obj({"id": UUID})}), "Created.", "201"), throttle=["conversations", "messages"])
op("put", "/v1/remotes/orgs/{org}", "Orgs", "renameOrg", "Rename an org",
   params=[pref("Org")], body=json_body(obj({"name": t("string", null=True, maxLength=60, description="Null removes the name.")})),
   throttle="conversations")
op("post", "/v1/remotes/orgs/{org}/members", "Orgs", "addOrgMembers", "Add members",
   params=[pref("Org")],
   body=json_body(obj({"members": arr(t("string"), "Handles.", minItems=1, maxItems=99),
                       "share_history": t("boolean", "Let them read earlier messages.")}, ["members", "share_history"])),
   throttle=["conversations", "messages"])
op("put", "/v1/remotes/orgs/{org}/members/{member}", "Orgs", "updateOrgMemberRole", "Change a member's role",
   params=[pref("Org"), pref("Member")], body=json_body(obj({"role": ref("OrgRole")}, ["role"])), throttle="conversations")
op("delete", "/v1/remotes/orgs/{org}/members/{member}", "Orgs", "removeOrgMember", "Remove a member (or leave)",
   params=[pref("Org"), pref("Member")], throttle="conversations")
op("get", "/v1/remotes/orgs/{org}/messages", "Orgs", "getOrgThread", "Read an org's thread",
   "From where your history starts. Poll with `after` and `reactions_after`.",
   params=[pref("Org")] + thread_params, responses=ok(data_of(ref("OrgThread"))), throttle="conversations")
op("post", "/v1/remotes/orgs/{org}/messages", "Orgs", "sendOrgMessage", "Send a message to an org",
   params=[pref("Org")], body=json_or_multipart(message_create, "images_or_voice", ""), responses=msg_created,
   throttle="messages")
op("put", "/v1/remotes/orgs/{org}/read", "Orgs", "markOrgRead", "Mark read through a message",
   params=[pref("Org")], body=json_body(obj({"through": t("integer", minimum=0)}, ["through"])), throttle="conversations")
op("put", "/v1/remotes/orgs/{org}/typing", "Orgs", "sendOrgTyping", "Say you're typing", params=[pref("Org")],
   throttle="conversations")
op("post", "/v1/remotes/orgs/{org}/ping", "Orgs", "pingOrg", "Ping everyone in an org", params=[pref("Org")],
   responses=ok(ref("MessageResponse"), "Created.", "201"), throttle="pings")
op("post", "/v1/remotes/orgs/{org}/archive", "Orgs", "stashOrg", "Stash an org", params=[pref("Org")],
   throttle="conversations")
op("delete", "/v1/remotes/orgs/{org}/archive", "Orgs", "unstashOrg", "Unstash an org", params=[pref("Org")],
   throttle="conversations")
op("put", "/v1/remotes/orgs/{org}/mute", "Orgs", "muteOrg", "Mute or unmute an org", params=[pref("Org")],
   body=json_body(obj({"duration": t("string", enum=["hour", "tomorrow", "week", "forever", "off"])}, ["duration"])),
   responses=ok(obj({"muted_until_at": DATETIME_N})), throttle="conversations")
op("put", "/v1/remotes/orgs/{org}/pin", "Orgs", "pinOrg", "Pin or unpin an org", params=[pref("Org")],
   body=json_body(obj({"pinned": t("boolean")}, ["pinned"])), responses=ok(obj({"pinned_at": DATETIME_N})),
   throttle="conversations")

# ---- Calls (WebRTC) -------------------------------------------------------------------------

op("get", "/v1/remotes/call", "Calls", "getIncomingCalls", "Poll for calls",
   "The call ringing for you, and calls going on in your orgs.",
   responses=ok(obj({
       "call": nul(obj({"partner": ref("User"), "sdp": t("string", "The caller's SDP offer."), "is_muted": t("boolean")})),
       "org_calls": arr(obj({"org": obj({"id": UUID, "name": t("string", null=True)}), "started_at": t("integer"),
                             "is_ringing": t("boolean"), "is_muted": t("boolean"), "members": arr(ref("CallMember"))})),
   })), throttle="conversations", errors=["401", "403", "429"])
op("get", "/v1/remotes/@{partner}/call/ice-servers", "Calls", "getDirectCallIceServers", "Get TURN servers for a call",
   params=[pref("Partner")], responses=ok(ref("IceServers")), throttle="messages")
op("post", "/v1/remotes/@{partner}/call", "Calls", "startDirectCall", "Call the partner",
   "Rings them with your SDP offer.", params=[pref("Partner")],
   body=json_body(obj({"sdp": t("string", "SDP offer (starts with `v=0`).", maxLength=10000)}, ["sdp"])),
   throttle="messages")
op("get", "/v1/remotes/@{partner}/call", "Calls", "getOutgoingCall", "Poll your outgoing call",
   "While it rings; `answer` is set once they accept.", params=[pref("Partner")],
   responses=ok(obj({"call": nul(obj({"answer": t("string", null=True, description="SDP answer.")}))})),
   throttle="conversations")
op("put", "/v1/remotes/@{partner}/call", "Calls", "answerDirectCall", "Answer the partner's call",
   params=[pref("Partner")],
   body=json_body(obj({"sdp": t("string", "SDP answer (starts with `v=0`).", maxLength=10000)}, ["sdp"])),
   throttle="conversations")
op("delete", "/v1/remotes/@{partner}/call", "Calls", "endDirectCall", "Decline, cancel or end a call",
   params=[pref("Partner")],
   body=json_body(obj({"failed": t("boolean", "The call failed rather than being declined.")}), required=False),
   throttle="conversations")
op("get", "/v1/remotes/orgs/{org}/call/ice-servers", "Calls", "getOrgCallIceServers", "Get TURN servers for an org call",
   params=[pref("Org")], responses=ok(ref("IceServers")), throttle="messages")
op("post", "/v1/remotes/orgs/{org}/call", "Calls", "joinOrgCall", "Start or join an org's call",
   "Up to 8 people. `call` is null if it filled up in between.", params=[pref("Org")],
   responses=ok(obj({"call": nul(ref("OrgCall"))}), "Joined.", "201"), throttle="messages")
op("put", "/v1/remotes/orgs/{org}/call", "Calls", "checkInOrgCall", "Check in to an org's call",
   "Every couple of seconds: hand over your signals, pick up the others'.", params=[pref("Org")],
   body=json_body(obj({"signals": arr(ref("CallSignal"), maxItems=8)}, ["signals"])),
   responses=ok(obj({"call": nul(ref("OrgCall"))})), throttle="conversations")
op("delete", "/v1/remotes/orgs/{org}/call", "Calls", "leaveOrgCall", "Leave an org's call", params=[pref("Org")],
   throttle="conversations")

# ---- Apps ---------------------------------------------------------------------------------

op("get", "/v1/apps/mac", "Apps", "getMacAppRelease", "Latest Mac app release",
   "Unsigned on purpose, so update checks send nothing about the user. `data` is null until a release is published.",
   auth="none", responses=ok(obj({"data": nul(ref("MacAppRelease"))}, ["data"])), errors=["429"])

# ---- CLI ------------------------------------------------------------------------------------

op("post", "/cli/key-lookups", "CLI", "lookupCliKey", "Find which of your SSH keys belongs to a /dev/null user",
   "Send up to 20 OpenSSH public keys, one per line. Answers with the first one on the GitHub account of a /dev/null "
   "user, so the script only asks the agent to sign with that key. Reads the database only (no GitHub call).",
   auth="none",
   body={"required": True, "content": {"text/plain": {"schema": t("string", example="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA… you@host")}}},
   responses={"200": {"description": "The matching public key.",
                      "content": {"text/plain": {"schema": t("string")}}},
              "404": {"description": "None of the keys belong to a /dev/null user (plain-text help message).",
                      "content": {"text/plain": {"schema": t("string")}}}},
   throttle="cli-key-lookups", errors=["429"])

op("post", "/cli/commits", "CLI", "createCliCommit", "Post a commit from the terminal",
   "What `curl -fsSL https://dev-null.sh/commit | bash -s -- 'Hello world!'` calls. No account or device needed: "
   "sign with an SSH key that's on your GitHub account.\n\n"
   "**Payload** (the exact bytes signed and sent):\n\n"
   "```\n<unix timestamp>\\n<nonce>\\n<reply-to hash or link, or empty>\\n<body>\n```\n\n"
   "With images, a line of comma-separated SHA-256 hex hashes (in attachment order) goes before the body:\n\n"
   "```\n<unix timestamp>\\n<nonce>\\n<reply-to>\\n<sha256,sha256>\\n<body>\n```\n\n"
   "Sign with `ssh-keygen -Y sign -n devnull-commit -f <key> payload` (namespace `devnull-commit-images` with images) "
   "and send the base64 inside the armor (no BEGIN/END lines, no newlines) as `X-SSH-Signature`.\n\n"
   "Responses are always **plain text**, errors included.",
   auth="cli",
   body={"required": True, "content": {
       "text/plain": {"schema": t("string", "The signed payload.",
                                  example="1762790400\n9f86d081884c7d659a2feaa0c55ad015\n\nHello from the terminal!")},
       "multipart/form-data": {"schema": obj({
           "payload": t("string", "The signed payload, as a file part.", contentMediaType="text/plain"),
           "images[]": arr(t("string", contentMediaType="image/*"), "JPEG, PNG or WebP; up to 3; 10 MB each.", maxItems=3),
       }, ["payload"])},
   }},
   responses={
       "201": {"description": "Committed.", "content": {"text/plain": {"schema": t("string", example=
               "Committed: https://dev-null.sh/@you/commits/… (pending review, only you can see it until it is approved)\n")}}},
       "401": {"description": "Bad, expired or replayed signature, or the key isn't on a /dev/null user's GitHub account.",
               "content": {"text/plain": {"schema": t("string")}}},
       "403": {"description": "Banned, timed out, or the commit rules must be read on the web first.",
               "content": {"text/plain": {"schema": t("string")}}},
       "422": {"description": "Validation failed (first message only).", "content": {"text/plain": {"schema": t("string")}}},
       "429": {"description": "10 commits a minute.", "headers": {"Retry-After": {"schema": t("integer")}},
               "content": {"text/plain": {"schema": t("string")}}},
       "503": {"description": "GitHub couldn't be reached to check the key.", "content": {"text/plain": {"schema": t("string")}}},
   },
   throttle="commits", errors=[])

# ---------------------------------------------------------------- document

DESCRIPTION = f"""
The API behind the /dev/null mobile, Mac and terminal apps, documented from the server source
([nunomaduro/dev-null.sh@{SOURCE_COMMIT[:7]}](https://github.com/nunomaduro/dev-null.sh/tree/{SOURCE_COMMIT}), {SOURCE_DATE}).

There are two APIs under `https://dev-null.sh/api`:

- **`/v1`**: JSON. The public read endpoints work without auth. Everything else is a request signed with an
  SSH key the user approved as a device.
- **`/cli`**: plain text. It's what the `devnull commit` script uses, signed with any SSH key on the author's GitHub account.

## Quick start

```sh
curl -s https://dev-null.sh/api/v1/users/nunomaduro
curl -s https://dev-null.sh/api/v1/users/nunomaduro/commits
curl -s "https://dev-null.sh/api/v1/users/nunomaduro/commits?replies=1"
curl -s https://dev-null.sh/api/v1/commits/01a1c63c-ae57-70cc-adf3-2298cc075627
```

Public endpoints: `GET /v1/users/{{handle}}`, `/v1/users/{{handle}}/commits`, `/v1/commits/{{commit}}`,
`/v1/commits/{{commit}}/related`, `/v1/organizations/{{handle}}` (and its `/commits` and `/mentions`), `/v1/apps/mac`.

## Authentication

There are no tokens or passwords. Each request is signed with an SSH key.

### Signed requests (`/v1`)

Build this message, with exactly four `\\n` separators, so five fields:

```
<unix timestamp>\\n<nonce>\\n<METHOD>\\n<path and query>\\n<body>
```

- **timestamp**: Unix seconds, within ±300 s of the server clock.
- **nonce**: 32 lowercase hex characters (16 random bytes). Each nonce can be used once.
- **METHOD**: uppercase, e.g. `GET`.
- **path and query**: the request URI as sent, e.g. `/api/v1/log/latest?cursor=abc`.
- **body**: the raw JSON body. Use an empty string for requests without one. Signed bodies **must be JSON**;
  form-encoded bodies are rejected.

Sign it as an SSHSIG with namespace **`devnull-api`**:

```sh
ssh-keygen -Y sign -n devnull-api -f ~/.ssh/id_ed25519 message
```

Then send these headers:

| header | value |
|---|---|
| `X-Devnull-Timestamp` | the timestamp |
| `X-Devnull-Nonce` | the nonce |
| `X-SSH-Signature` | the base64 inside the armor, without the `-----BEGIN/END-----` lines or newlines |

On public endpoints, a request with **any** of these headers has to verify. It never falls back to the guest view.

### Requests with files

Commits, reports and messages can carry images, and messages can carry a voice note. To attach files, send
`multipart/form-data` with:

- `payload`: the JSON body, as a file part;
- `images[]`: up to 3 files, **or** `voice`: one file.

No other fields are allowed. The signed message gets one more line, before the body: the comma-separated SHA-256 hex
hashes of the files, in the order attached. The namespace becomes **`devnull-api-images`**:

```
<timestamp>\\n<nonce>\\n<METHOD>\\n<path>\\n<sha256[,sha256…]>\\n<payload JSON>
```

### Signing in (approving a key as a device)

The flow is OAuth-style with PKCE (RFC 7636 / RFC 8252):

1. Generate an SSH key pair on the device, and a PKCE `code_verifier` (43-128 chars) with
   `code_challenge = BASE64URL(SHA256(code_verifier))`.
2. Open `https://dev-null.sh/mobile/authorize` in a browser with these query parameters: `fingerprint` (`SHA256:…`
   of the key), `device_name`, `code_challenge`, `code_challenge_method=S256`, `state`, and a `redirect_uri` that
   starts with `devnull://` or is `http://127.0.0.1:<port>` (for CLIs). `app_id` and `app_name` are optional.
   The user signs in with GitHub and approves. The browser is then redirected to `redirect_uri?code=…&state=…`
   (or `error=access_denied`).
3. Call `POST /v1/devices` with `{{"code", "code_verifier"}}`, **signed with the new key**. The key is approved, and the
   response is the same as `GET /v1/me`.

Users can see and revoke their devices at Settings → Devices, or with `GET/DELETE /v1/me/devices`.

### CLI commits (`/cli`)

See `POST /cli/commits`. This flow has no device step: the key just needs to be on the author's GitHub account.

## Pagination

Most lists use **cursor pagination**: `{{ data, links, meta }}`. Follow `links.next`, or pass `meta.next_cursor` as
`?cursor=`, until it's `null`. Page sizes are fixed: 20 for commits, 30 for followers/following.
`GET /v1/scheduled-commits` uses page numbers instead (`?page=`, with `meta.total`).

Single resources are wrapped as `{{ "data": … }}`. Some endpoints add top-level keys next to `data`, such as `log` or
`unread_notifications_count`.

## Errors

| status | body |
|---|---|
| 400 / 401 / 403 / 404 / 422 / 429 / 503 from the signed API | `{{ "message", "code" }}`. See `ApiErrorCode` |
| 422 validation | `{{ "message", "errors": {{ field: [messages] }} }}` |
| others | `{{ "message" }}` |

Content that is missing, deleted or hidden from you returns the same 404. Remotes endpoints return 404 when Remotes
are off for you, or when you can't see the conversation.

## Rate limits

`/v1` allows **120 requests/min per user** for signed requests and **60/min per IP** for unsigned ones. Some actions
have their own limits too: commits 10/min, searches 15/min, messages 30/min, pings 3/min, follows 30/min,
stars 60/min, pins 20/min, reports 5/min. Each operation lists the limits that apply to it. Signature failures are
capped at 60/min per IP. A 429 response includes `Retry-After`.

## Conventions

- Timestamps are ISO 8601 UTC (`2026-11-10T16:26:27Z`).
- Commits, users, devices and notifications have UUID ids. Messages have integer ids.
- A user's handle is their GitHub login. Organizations share the `@handle` namespace with users.
- Commit bodies are limited to 4,000 characters, and links count at their display length.
- This documentation is unofficial and community-written. The server code is the source of truth.
""".strip()

TAGS = [
    ("Users", "Profiles, their commits, and following, muting and blocking."),
    ("Organizations", "GitHub organizations' pages."),
    ("Commits", "Posting, reading, starring, pinning, translating and reporting commits."),
    ("Log", "The Following / Latest / Trending feeds."),
    ("Scheduled commits", "Commits queued for later."),
    ("Search", "People, organizations, commits (semantic), mentions and issues."),
    ("Me", "The signed-in user."),
    ("Settings", "Private preferences."),
    ("Devices", "Signing in, devices and push tokens."),
    ("Notifications", "Grouped notifications: follows, replies, mentions, stars, moderation."),
    ("Remotes", "Direct messages: inbox, threads, messages and reactions."),
    ("Orgs", "Group conversations (\"orgs\" in Remotes, not GitHub organizations)."),
    ("Calls", "Voice/video calls over WebRTC, signalled by polling."),
    ("Apps", "Release info for the native apps."),
    ("CLI", "The plain-text API the `devnull commit` script uses."),
]

doc = {
    "openapi": "3.1.0",
    "info": {
        "title": "/dev/null API",
        "version": f"{SOURCE_DATE.replace('-', '.')}-{SOURCE_COMMIT[:8]}",
        "summary": "The social network for developers: commits, the log, Remotes.",
        "description": DESCRIPTION,
        "contact": {"name": "/dev/null", "url": "https://dev-null.sh/about"},
        "termsOfService": "https://dev-null.sh/terms",
    },
    "servers": [{"url": "https://dev-null.sh/api", "description": "Production"}],
    "externalDocs": {"description": "Server source", "url": "https://github.com/nunomaduro/dev-null.sh"},
    "tags": [{"name": n, **({"description": d} if d else {})} for n, d in TAGS],
    "paths": dict(sorted(paths.items(), key=lambda kv: ([n for n, _ in TAGS].index(next(iter(kv[1].values()))["tags"][0]), kv[0]))),
    "components": {
        "securitySchemes": {
            "sshSignature": {"type": "apiKey", "in": "header", "name": "X-SSH-Signature",
                             "description": "Base64 SSHSIG (namespace `devnull-api`, or `devnull-api-images` with files) of "
                                            "`<timestamp>\\n<nonce>\\n<METHOD>\\n<path and query>\\n<body>`, made with a key "
                                            "approved as a device. Sent together with `X-Devnull-Timestamp` and `X-Devnull-Nonce`."},
            "devnullTimestamp": {"type": "apiKey", "in": "header", "name": "X-Devnull-Timestamp",
                                 "description": "Unix seconds, within ±300 s of the server clock."},
            "devnullNonce": {"type": "apiKey", "in": "header", "name": "X-Devnull-Nonce",
                             "description": "32 lowercase hex characters, single use."},
            "cliSignature": {"type": "apiKey", "in": "header", "name": "X-SSH-Signature",
                             "description": "Base64 SSHSIG (namespace `devnull-commit` or `devnull-commit-images`) of the "
                                            "raw payload, made with an SSH key on the author's GitHub account."},
        },
        "parameters": components_parameters,
        "responses": R,
        "schemas": schemas,
    },
}

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
out.mkdir(parents=True, exist_ok=True)


class Dumper(yaml.SafeDumper):
    pass


def str_presenter(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


Dumper.add_representer(str, str_presenter)
Dumper.ignore_aliases = lambda *a: True

(out / "openapi.yaml").write_text(yaml.dump(doc, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120))
(out / "openapi.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2))
n_ops = sum(len(v) for v in paths.values())
print(f"{len(paths)} paths, {n_ops} operations, {len(schemas)} schemas")
