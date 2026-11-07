"use client";

import { useState } from "react";

import {
  ErrorNotice,
  SavedNotice,
  ScreenHeader,
  SELECT_STYLE,
  errorMessage,
  useLoaded,
} from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { addPalette, getAssets, uploadAsset } from "@/lib/admin";
import type { Asset } from "@/lib/contracts";

function colours(asset: Asset): string[] {
  const value = asset.meta.colours;
  return Array.isArray(value) ? value.map(String) : [];
}

function assetName(asset: Asset): string {
  const name = asset.meta.name;
  return typeof name === "string" ? name : asset.file_ref || asset.id;
}

export function AssetsScreen() {
  const { data: assets, error: loadError, reload } = useLoaded(getAssets);
  const [palette, setPalette] = useState("");
  const [kind, setKind] = useState<"logo" | "image">("logo");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(work: () => Promise<Asset>, done: () => void) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const asset = await work();
      setNotice(`Added ${asset.id}.`);
      done();
      reload();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const list = assets ?? [];
  const palettes = list.filter((asset) => asset.kind === "palette");
  const files = list.filter((asset) => asset.kind !== "palette");

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="Assets"
        summary="The approved logos, images and colours the Visual agent checks against."
      />
      <ErrorNotice message={error ?? loadError} />
      {notice && <SavedNotice>{notice}</SavedNotice>}

      <section aria-labelledby="palette-heading" className="mt-6">
        <h2 id="palette-heading" className="text-lg font-semibold">
          Palettes
        </h2>
        <ul className="mt-3 flex flex-col gap-3">
          {palettes.map((asset) => (
            <li key={asset.id} className="rounded-lg border p-4">
              <p className="text-sm font-medium">{asset.id}</p>
              <ul className="mt-2 flex flex-wrap gap-3">
                {colours(asset).map((colour) => (
                  <li key={colour} className="flex items-center gap-2 text-sm">
                    <span
                      aria-hidden="true"
                      className="size-6 rounded border"
                      style={{ backgroundColor: colour }}
                    />
                    {colour}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            run(
              () =>
                addPalette(
                  palette
                    .split(/[\s,]+/)
                    .map((colour) => colour.trim())
                    .filter(Boolean),
                ),
              () => setPalette(""),
            );
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="palette-colours">
              New palette, as #RRGGBB colours
            </Label>
            <Input
              id="palette-colours"
              className="w-80"
              placeholder="#12343B, #E0A800"
              required
              value={palette}
              onChange={(event) => setPalette(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy}>
            Add palette
          </Button>
        </form>
      </section>

      <section aria-labelledby="files-heading" className="mt-8">
        <h2 id="files-heading" className="text-lg font-semibold">
          Logos and images
        </h2>
        {assets && files.length === 0 && (
          <p className="mt-3 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            No logos or images yet.
          </p>
        )}
        <ul className="mt-3 flex flex-col gap-2">
          {files.map((asset) => (
            <li
              key={asset.id}
              className="flex flex-wrap gap-2 rounded-lg border p-3 text-sm"
            >
              <span className="font-medium">{asset.id}</span>
              <span className="capitalize text-muted-foreground">
                {asset.kind}
              </span>
              <span>{assetName(asset)}</span>
            </li>
          ))}
        </ul>
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (file)
              run(
                () => uploadAsset(kind, file),
                () => setFile(null),
              );
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="asset-kind">Kind</Label>
            <select
              id="asset-kind"
              className={SELECT_STYLE}
              value={kind}
              onChange={(event) =>
                setKind(event.target.value as "logo" | "image")
              }
            >
              <option value="logo">Logo</option>
              <option value="image">Image</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="asset-file">PNG or JPEG file</Label>
            <Input
              id="asset-file"
              type="file"
              accept="image/png,image/jpeg"
              required
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <Button type="submit" disabled={busy || !file}>
            Upload
          </Button>
        </form>
      </section>
    </div>
  );
}
