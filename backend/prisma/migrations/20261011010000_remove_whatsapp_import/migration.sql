-- The application no longer ingests WhatsApp (Cloud API webhook, chat-export upload, watched folder, Google Drive).
-- Conversations happen in the in-app chat. Messages already stored (ChatMessage / ChatUpload) are kept.
DROP TABLE IF EXISTS "WhatsappSource";
DROP TABLE IF EXISTS "GoogleConnection";
DROP TABLE IF EXISTS "DriveImport";
