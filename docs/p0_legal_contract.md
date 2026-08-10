# P0 legal integration contract

Contract inventory: `P0-LEGAL-CONTRACT-v1`
Inventory date: `2026-08-10`
Legal document version/date: awaiting an explicitly approved product/legal source
Responsible owner: product/legal

This document records the technical integration boundary. It is not legal copy and
does not approve, replace, or interpret any public legal text.

## Canonical public documents

| Document | Canonical URL | Public UI locations |
| --- | --- | --- |
| Privacy policy | `https://www.restos.space/privacy.html` | Login, registration SMS, password-reset SMS, account creation, invitation registration |
| Personal-data processing | `https://www.restos.space/personal-data.html` | Login, registration SMS, password-reset SMS, account creation, invitation registration |
| Terms of use | `https://www.restos.space/terms.html` | Login, registration SMS, password-reset SMS, account creation, invitation registration |

The URLs are compile-time HTTPS links on the exact allowlisted host. They are not
derived from account, provider, backend, or user input. Public documents must remain
available without authentication, cookies, or query credentials.

## Registration data and purposes requiring approved wording

The standalone Account flow processes the following categories:

- phone number, including normalization and a non-reversible lookup digest;
- one-time authorization code, stored only as a digest;
- display name;
- password, stored only through the existing password-hash contract;
- device identity and proof-of-possession material required by the versioned device protocol;
- rotating web-session and access-token state after successful registration.

The phone number is personal data. Its current product purposes are Account
registration, authentication, and password recovery. Registration and recovery use
authorization OTP SMS. Delivery is delegated to the configured SMS provider; the
current provider contract is SMS Aero with the exact approved sender name `SMS Aero`.
Provider credentials remain external runtime secrets.

There are no marketing SMS in this flow. No newsletter or marketing consent is
requested, implied, stored, or combined with Account registration.

## Action contexts

| Context | User action | Technical behavior |
| --- | --- | --- |
| `registration_sms` | Explicit click on “Получить код” | Requests one bounded registration OTP challenge |
| `password_reset_sms` | Explicit click on “Получить код” | Requests one bounded recovery OTP challenge |
| `account_creation` | Explicit click on “Создать аккаунт” | Completes the already verified registration flow |
| `invitation_registration` | Explicit invitation-flow actions | Uses the same canonical documents and no separate legal copy |
| `login` | Password or passkey login | Keeps canonical documents available; does not request a new consent |

Opening or rendering a legal link must not request an SMS, mutate a challenge, or
write consent state. No consent timestamp or schema is authorized by this contract.

## Public-copy approval slots

Production UI currently exposes only the canonical document titles and URLs. Short
notice/acceptance wording is intentionally absent until product/legal supplies an
explicitly approved source containing:

- final short copy for `registration_sms`;
- final short copy for `password_reset_sms`;
- final acceptance copy, if required, for `account_creation`;
- confirmation that `invitation_registration` uses the same or a separately approved copy;
- legal document version and effective date;
- final decision on whether any explicit checkbox is required.

No checkbox, consent persistence, migration, or speculative record may be added
without that decision.

## Existing public-site text inventory

The following supplied inventory remains subject to product/legal review and must not
be rewritten by engineering without an approved source:

- privacy: “Сервис находится в разработке; документ будет уточняться перед публичным запуском.”;
- personal data: “Информационная версия для этапа разработки. Перед публичным запуском текст подлежит юридической проверке.”;
- terms: “RestOS находится на этапе разработки и закрытого тестирования.”;
- terms: “Публичная оферта в настоящий момент не размещена.”;
- terms: “До официального запуска отдельные функции могут изменяться, временно ограничиваться или быть недоступны.”;
- terms: “Условия коммерческого использования будут опубликованы отдельно.”;
- home: “В разработке”;
- home: “Сервис находится на этапе разработки и закрытого тестирования.”;
- home: “© 2026 RestOS. Проект находится в разработке.”

Removal or replacement is a separate product/legal-approved publication operation.

## Release boundary

P0 technical acceptance may use only fake/controlled SMS delivery. P0 legal acceptance
requires approved text, publication of all three final documents, and a green public
site audit. Real-SMS acceptance additionally requires written confirmation that SMS
Aero API moderation is disabled and a separately authorized, bounded pilot operation.
