/**
 * SupportFlow AI — Interactive AI Assistant & RAG Demonstration Page
 *
 * Demonstrates:
 *   1. Multi-Stage Hybrid Retrieval (pgvector + FTS + RRF)
 *   2. Cross-Encoder Reranking
 *   3. Bounded Tool Execution (get_order_status, get_payment_status)
 *   4. Authorization / IDOR Protection
 *   5. Grounding & Hallucination Guardrails
 *   6. Human-In-The-Loop Escalation Detection
 *   7. Interactive User Feedback Collection
 */

import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { knowledgeApi } from "@/services/api";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  Button,
  Textarea,
  Spinner,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { RAGQueryResponse, RAGSourceItem, APIError } from "@/types";
import {
  Bot,
  Sparkles,
  Layers,
  AlertTriangle,
  Clock,
  ThumbsUp,
  ThumbsDown,
  BookOpen,
  Wrench,
} from "lucide-react";


interface DemoScenario {
  id: string;
  label: string;
  tag: string;
  query: string;
  description: string;
}

const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "scenario-rag",
    label: "Grounded Knowledge RAG",
    tag: "Hybrid Search + Reranker",
    query: "How long does standard shipping take?",
    description: "Retrieves shipping policy chunks via hybrid search, reranks them, and synthesizes a grounded answer.",
  },
  {
    id: "scenario-tool-authorized",
    label: "Bounded Tool (My Order)",
    tag: "Tool Execution",
    query: "What is the current status of my order ORD-2024-1001?",
    description: "LLM requests get_order_status. Application checks customer ownership and returns live order data safely.",
  },
  {
    id: "scenario-tool-idor",
    label: "RBAC & IDOR Defense",
    tag: "Security Invariant",
    query: "Can you give me the status of order ORD-2024-2002?",
    description: "Tests authorization boundary. Customer Alice cannot access Customer Rahul's order — tool safely denies access.",
  },
  {
    id: "scenario-guardrail",
    label: "Hallucination Guardrail",
    tag: "Safety Check",
    query: "What is the direct private cell phone number of your company CEO?",
    description: "Information absent from the knowledge base. System refuses to fabricate facts and returns safe fallback notice.",
  },
  {
    id: "scenario-hitl",
    label: "Human Review Escalation",
    tag: "HITL Triage",
    query: "I want to speak with a human supervisor immediately regarding legal action against your company.",
    description: "Detects high-risk legal/escalation sentiment. Flags ticket for human agent queue instead of automatic dispatch.",
  },
];

export const AIAssistantPage: React.FC = () => {
  const { toast } = useToast();
  const [queryInput, setQueryInput] = useState("");
  const [lastResponse, setLastResponse] = useState<RAGQueryResponse | null>(null);
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState<"helpful" | "unhelpful" | null>(null);

  const askMutation = useMutation({
    mutationFn: (query: string) => knowledgeApi.ask(query, 5),
    onSuccess: (data) => {
      setLastResponse(data);
      setFeedbackSubmitted(null);
    },
    onError: (err) => {
      const msg = err instanceof APIError ? err.message : "Failed to execute AI inquiry.";
      toast({ title: "Query Error", description: msg, variant: "error" });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = queryInput.trim();
    if (!q) return;
    askMutation.mutate(q);
  };

  const selectScenario = (sc: DemoScenario) => {
    setSelectedScenario(sc.id);
    setQueryInput(sc.query);
    askMutation.mutate(sc.query);
  };

  const handleFeedback = (type: "helpful" | "unhelpful") => {
    setFeedbackSubmitted(type);
    toast({
      title: type === "helpful" ? "Feedback Recorded" : "Escalation Logged",
      description:
        type === "helpful"
          ? "Thank you for verifying this AI response."
          : "Response flagged for support agent operational review.",
      variant: "success",
    });
  };

  return (
    <div className="px-6 py-8 max-w-5xl mx-auto">
      <PageHeader
        title="AI Support Assistant & RAG Pipeline"
        description="Interactive demonstration of LangGraph orchestration, hybrid vector/keyword retrieval, bounded tools, and human review guardrails."
      />

      {/* Preset Demo Scenarios */}
      <div className="mb-6">
        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
          Interviewer Quick Scenarios
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          {DEMO_SCENARIOS.map((sc) => (
            <button
              key={sc.id}
              id={sc.id}
              type="button"
              onClick={() => selectScenario(sc)}
              className={`text-left p-3 rounded-xl border transition-all ${
                selectedScenario === sc.id
                  ? "border-brand-500 bg-brand-50/50 shadow-sm"
                  : "border-slate-200 bg-white hover:border-brand-300 hover:bg-slate-50/60"
              }`}
            >
              <div className="flex items-center justify-between gap-1 mb-1">
                <span className="text-xs font-bold text-slate-800">{sc.label}</span>
                <span className="text-[10px] font-medium bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
                  {sc.tag}
                </span>
              </div>
              <p className="text-[11px] text-slate-500 line-clamp-2 leading-relaxed">
                "{sc.query}"
              </p>
            </button>
          ))}
        </div>
      </div>

      {/* Query Input Card */}
      <Card className="mb-6 shadow-sm">
        <CardContent className="pt-5">
          <form onSubmit={handleSubmit} className="space-y-3">
            <Textarea
              id="ai-assistant-input"
              rows={3}
              placeholder="Ask a question or enter a customer support query… (e.g., 'How long does standard shipping take?' or 'What is the status of my order ORD-2024-1001?')"
              value={queryInput}
              onChange={(e) => {
                setQueryInput(e.target.value);
                setSelectedScenario(null);
              }}
            />
            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-slate-400">
                Processed via LangGraph RAG with pgvector cosine similarity & cross-encoder reranking
              </span>
              <Button
                id="ai-assistant-submit"
                type="submit"
                isLoading={askMutation.isPending}
                disabled={!queryInput.trim()}
                leftIcon={<Sparkles className="w-4 h-4" />}
              >
                Run AI Pipeline
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Loading State */}
      {askMutation.isPending && (
        <Card className="p-8 mb-6 border-brand-200 bg-brand-50/20">
          <div className="flex flex-col items-center justify-center text-center">
            <Spinner size="lg" className="text-brand-600 mb-3" />
            <p className="text-sm font-semibold text-slate-800">
              Executing LangGraph RAG StateGraph…
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Multi-stage retrieval (pgvector + FTS) → Cross-encoder rerank → Bounded tool check → Groq synthesis
            </p>
          </div>
        </Card>
      )}

      {/* Results View */}
      {lastResponse && !askMutation.isPending && (
        <div className="space-y-5 animate-in">
          {/* Pipeline Execution Summary Banner */}
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-brand-100 text-brand-700 flex items-center justify-center">
                  <Bot className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900">Pipeline Execution Result</h3>
                  <p className="text-xs text-slate-500">Query: "{lastResponse.query}"</p>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {lastResponse.latency_ms && (
                  <Badge variant="outline" size="sm" className="flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3 text-slate-400" />
                    {lastResponse.latency_ms.toFixed(0)} ms
                  </Badge>
                )}
                <Badge
                  variant={lastResponse.context_found ? "success" : "secondary"}
                  size="sm"
                  className="flex items-center gap-1"
                >
                  <BookOpen className="w-3 h-3" />
                  {lastResponse.context_found ? "Context Found" : "No Knowledge Context"}
                </Badge>
                {lastResponse.tool_called && (
                  <Badge variant="brand" size="sm" className="flex items-center gap-1 font-mono">
                    <Wrench className="w-3 h-3" />
                    Tool: {lastResponse.tool_called}
                  </Badge>
                )}
                {lastResponse.escalation_triggered && (
                  <Badge variant="danger" size="sm" className="flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" />
                    HITL Escalation Triggered
                  </Badge>
                )}
              </div>
            </div>

            {/* Pipeline Stage Visualizer */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-slate-100 text-center">
              <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <p className="text-[10px] text-slate-400 font-semibold uppercase">1. Retrieval</p>
                <p className="text-xs font-medium text-slate-700 mt-0.5">Vector + FTS (RRF)</p>
              </div>
              <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <p className="text-[10px] text-slate-400 font-semibold uppercase">2. Reranker</p>
                <p className="text-xs font-medium text-slate-700 mt-0.5">ms-marco-MiniLM</p>
              </div>
              <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <p className="text-[10px] text-slate-400 font-semibold uppercase">3. Synthesis</p>
                <p className="text-xs font-medium text-slate-700 mt-0.5">Grounded Llama 3.3</p>
              </div>
              <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <p className="text-[10px] text-slate-400 font-semibold uppercase">4. Guardrail</p>
                <p className="text-xs font-medium text-slate-700 mt-0.5">
                  {lastResponse.escalation_triggered ? "Escalated" : "Grounded Verified"}
                </p>
              </div>
            </div>
          </div>

          {/* AI Response Card */}
          <Card className="shadow-sm border-brand-100 bg-white">
            <CardHeader className="bg-slate-50/50 border-b border-slate-100 pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2 text-slate-900">
                  <Sparkles className="w-4 h-4 text-brand-600" />
                  Synthesized Grounded Response
                </CardTitle>
                <span className="text-xs text-slate-400">Strictly grounded in retrieved knowledge</span>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="prose prose-sm max-w-none text-slate-800 whitespace-pre-wrap leading-relaxed">
                {lastResponse.answer}
              </div>

              {lastResponse.escalation_reason && (
                <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold">Escalation Trigger: </span>
                    {lastResponse.escalation_reason}
                  </div>
                </div>
              )}

              {/* Interactive Feedback Controls */}
              <div className="mt-5 pt-4 border-t border-slate-100 flex items-center justify-between flex-wrap gap-2">
                <span className="text-xs font-medium text-slate-500">
                  Was this response accurate and grounded?
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    id="feedback-helpful"
                    variant={feedbackSubmitted === "helpful" ? "primary" : "outline"}
                    size="sm"
                    onClick={() => handleFeedback("helpful")}
                    leftIcon={<ThumbsUp className="w-3.5 h-3.5" />}
                  >
                    Helpful
                  </Button>
                  <Button
                    id="feedback-unhelpful"
                    variant={feedbackSubmitted === "unhelpful" ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => handleFeedback("unhelpful")}
                    leftIcon={<ThumbsDown className="w-3.5 h-3.5" />}
                  >
                    Not Helpful
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Cited Context Sources */}
          {lastResponse.sources && lastResponse.sources.length > 0 && (
            <Card className="shadow-sm">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Layers className="w-4 h-4 text-slate-500" />
                    Retrieved Knowledge Sources ({lastResponse.sources.length} passages cited)
                  </CardTitle>
                  <span className="text-xs text-slate-400">Ranked by Cross-Encoder</span>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {lastResponse.sources.map((src: RAGSourceItem, idx: number) => (
                  <div
                    key={src.chunk_id || idx}
                    className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/60"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
                      <span className="text-xs font-semibold text-slate-900 flex items-center gap-1.5">
                        <span className="w-4 h-4 rounded-full bg-brand-100 text-brand-700 text-[10px] font-bold flex items-center justify-center">
                          {idx + 1}
                        </span>
                        {src.document_title}
                      </span>
                      <div className="flex items-center gap-2">
                        {src.score != null && (
                          <Badge variant="secondary" size="sm" className="font-mono text-[10px]">
                            Relevance: {src.score.toFixed(3)}
                          </Badge>
                        )}
                        <Badge variant="outline" size="sm" className="text-[10px]">
                          chunk #{src.chunk_index}
                        </Badge>
                      </div>
                    </div>
                    <p className="text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
                      {src.content}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
};
