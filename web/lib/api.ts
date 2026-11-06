const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const GENERIC_ERROR = "Something went wrong. Try again in a moment.";

export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      // The session lives in an httpOnly cookie, so scripts never see the token.
      credentials: "include",
      // The browser sets the multipart boundary itself for FormData.
      headers:
        init?.body instanceof FormData
          ? init.headers
          : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "We couldn't reach the server. Try again in a moment.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    // FastAPI's own validation errors are a list, which isn't fit to show anyone.
    const detail = body?.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string" ? detail : GENERIC_ERROR,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
