import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

function parseMessageContent(content: string) {
  const imageMatch = content.match(/<img\b[^>]*\bsrc=(['"])(.*?)\1[^>]*>/i);
  const imageUrl = imageMatch?.[2];
  const text = imageUrl
    ? content.replace(imageMatch[0], "").trim()
    : content;

  return { text, imageUrl };
}

export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const { text, imageUrl } = parseMessageContent(message.content);

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-3 text-sm shadow-sm",
          isUser
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : "bg-muted text-foreground rounded-bl-sm border border-border/50"
        )}
      >
        {message.image_base64 && (
          <img
            src={`data:image/jpeg;base64,${message.image_base64}`}
            alt="uploaded"
            className="mb-2 max-h-48 rounded-lg object-contain"
          />
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap">{text}</p>
        ) : (
          <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-1 prose-ul:my-1 prose-li:my-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        )}
        {imageUrl && (
          <img
            src={imageUrl}
            alt="Processed result"
            className="mt-3 max-w-full rounded-lg border"
          />
        )}
      </div>
    </div>
  );
}
