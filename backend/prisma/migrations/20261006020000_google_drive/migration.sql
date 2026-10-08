-- CreateTable
CREATE TABLE "GoogleConnection" (
    "id" TEXT NOT NULL DEFAULT 'singleton',
    "connectedById" TEXT NOT NULL,
    "accountEmail" TEXT,
    "refreshTokenEnc" TEXT NOT NULL,
    "scope" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'CONNECTED',
    "lastSyncAt" TIMESTAMP(3),
    "lastError" TEXT,
    "connectedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "GoogleConnection_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DriveImport" (
    "fileId" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "fileName" TEXT NOT NULL,
    "md5" TEXT,
    "modifiedTime" TEXT,
    "outcome" TEXT NOT NULL,
    "detail" TEXT,
    "importedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DriveImport_pkey" PRIMARY KEY ("fileId")
);

-- CreateIndex
CREATE INDEX "DriveImport_projectId_importedAt_idx" ON "DriveImport"("projectId", "importedAt");
