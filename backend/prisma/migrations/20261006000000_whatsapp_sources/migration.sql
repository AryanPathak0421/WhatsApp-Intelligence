-- CreateTable
CREATE TABLE "WhatsappSource" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "phoneNumberId" TEXT NOT NULL,
    "conversationKey" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "uploadId" TEXT NOT NULL,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "createdById" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastEventAt" TIMESTAMP(3),
    "messageCount" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "WhatsappSource_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "WhatsappSource_projectId_idx" ON "WhatsappSource"("projectId");

-- CreateIndex
CREATE UNIQUE INDEX "WhatsappSource_phoneNumberId_conversationKey_key" ON "WhatsappSource"("phoneNumberId", "conversationKey");

-- AddForeignKey
ALTER TABLE "WhatsappSource" ADD CONSTRAINT "WhatsappSource_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE CASCADE ON UPDATE CASCADE;
