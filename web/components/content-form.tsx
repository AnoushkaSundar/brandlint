"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  ACCEPTED_FILES,
  CHANNELS,
  createContent,
  DATA_CLASSES,
} from "@/lib/content";

type Option = { value: string; label: string };

function SelectField({
  id,
  label,
  options,
  initial,
}: {
  id: string;
  label: string;
  options: Option[];
  initial: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Select name={id} items={options} defaultValue={initial}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function ContentForm() {
  const { user } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (user.role !== "creator") {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">New content</h1>
        <p className="mt-2 text-muted-foreground">
          Only creators can submit content.
        </p>
      </div>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const created = await createContent(new FormData(event.currentTarget));
      router.push(`/content/${created.id}`);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Something went wrong. Try again in a moment.",
      );
      setPending(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">New content</h1>
      <p className="mt-1 mb-6 text-muted-foreground">
        Paste your draft or upload a file, then start a review.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-destructive p-3 text-sm text-destructive"
          >
            {error}
          </p>
        )}

        <div className="flex flex-col gap-2">
          <Label htmlFor="title">Title</Label>
          <Input id="title" name="title" maxLength={255} required />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <SelectField
            id="channel"
            label="Channel"
            options={CHANNELS}
            initial="blog"
          />
          <SelectField
            id="data_class"
            label="Data class"
            options={DATA_CLASSES}
            initial="internal"
          />
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="source">Source</Label>
          <Input
            id="source"
            name="source"
            defaultValue={user.tag === "agency" ? "" : "in-house"}
            maxLength={255}
            aria-describedby="source-hint"
            required
          />
          <p id="source-hint" className="text-sm text-muted-foreground">
            Enter in-house, an agency name or an AI tool name.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="text">Paste your text</Label>
          <Textarea id="text" name="text" rows={10} />
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="file">Or upload a file</Label>
          <Input
            id="file"
            name="file"
            type="file"
            accept={ACCEPTED_FILES}
            aria-describedby="file-hint"
          />
          <p id="file-hint" className="text-sm text-muted-foreground">
            Text, HTML, DOCX, PDF, PNG or JPEG, up to 10 MB.
          </p>
        </div>

        <div className="flex gap-3">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Save draft"}
          </Button>
          <Button variant="outline" render={<Link href="/content" />}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
