import assert from "node:assert/strict";
import test from "node:test";

import { MAX_ATTACHMENT_BYTES, readAttachment } from "./attachments.ts";

/**
 * Only the size cap is covered. Everything past it needs `FileReader`, which is a browser API that
 * `node --test` does not provide, and stubbing it would pin the stub rather than the behaviour.
 *
 * The cap is the half worth testing anyway: it is the one branch that rejects a file the user picked,
 * and the composer's error path depends on it throwing rather than resolving.
 */
const fileOfSize = (bytes: number, name = "clip.mov") => ({ name, size: bytes, type: "video/quicktime" }) as File;

test("a file over the cap is rejected before it is read", async () => {
  await assert.rejects(() => readAttachment(fileOfSize(MAX_ATTACHMENT_BYTES + 1)), /caps attachments at 4MB/);
});

test("the rejection names the file and its size, so the transcript can say which one", async () => {
  await assert.rejects(
    () => readAttachment(fileOfSize(6 * 1024 * 1024, "holiday.mov")),
    (error: Error) => error.message.includes("holiday.mov") && error.message.includes("6.0MB"),
  );
});

test("a file exactly at the cap is not rejected by the size check", async () => {
  // It fails later on FileReader, which node has no implementation of — reaching that is the point:
  // the boundary is `>`, not `>=`, so a file exactly at the cap is allowed through.
  await assert.rejects(() => readAttachment(fileOfSize(MAX_ATTACHMENT_BYTES)), (error: Error) => !/caps attachments/.test(error.message));
});
