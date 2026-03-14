import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

interface ChatRequest {
  message: string;
  session_id?: string;
}

interface ChatResponse {
  content: string;
  session_id: string;
  tool_calls: string[];
  input_tokens: number;
  output_tokens: number;
}

export function useAdvisorChat() {
  const mutation = useMutation<ChatResponse, Error, ChatRequest>({
    mutationFn: (req) =>
      api.post("/advisor/chat", req).then((r) => r.data),
  });

  return {
    chat: mutation.mutateAsync,
    isLoading: mutation.isPending,
    error: mutation.error,
  };
}
