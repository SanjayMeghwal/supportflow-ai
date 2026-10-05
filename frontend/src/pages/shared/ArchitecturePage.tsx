/**
 * SupportFlow AI — System Architecture Explainer View
 *
 * Explains the end-to-end design, LangGraph RAG orchestration,
 * bounded tools, security invariants, and production infrastructure.
 */

import React from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  ShieldCheck,
  Server,
  Bot,
  Search,
  ArrowRight,
  Zap,
} from "lucide-react";


export const ArchitecturePage: React.FC = () => {
  return (
    <div className="px-6 py-8 max-w-5xl mx-auto space-y-8">
      <PageHeader
        title="System Architecture & Engineering Design"
        description="Production-oriented AI customer support platform built with FastAPI, LangGraph, pgvector, and bounded tools."
      />

      {/* Visual Pipeline Flowchart */}
      <Card className="shadow-sm border-brand-100 overflow-hidden">
        <CardHeader className="bg-slate-50 border-b border-slate-100">
          <CardTitle className="text-sm flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-brand-600" />
              End-to-End Inquiry & Support Lifecycle
            </span>
            <Badge variant="brand" size="sm">LangGraph RAG StateGraph</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-7 gap-2 items-center text-center">
            {/* Step 1 */}
            <div className="p-3 rounded-xl border border-slate-200 bg-slate-50">
              <div className="w-7 h-7 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                1
              </div>
              <p className="text-xs font-bold text-slate-800">Customer Inquiry</p>
              <p className="text-[10px] text-slate-500 mt-0.5">Ticket / Portal</p>
            </div>

            <div className="hidden md:flex justify-center text-slate-300">
              <ArrowRight className="w-5 h-5" />
            </div>

            {/* Step 2 */}
            <div className="p-3 rounded-xl border border-brand-200 bg-brand-50/40">
              <div className="w-7 h-7 rounded-lg bg-brand-600 text-white flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                2
              </div>
              <p className="text-xs font-bold text-slate-800">Hybrid Retrieval</p>
              <p className="text-[10px] text-slate-500 mt-0.5">pgvector + FTS (RRF)</p>
            </div>

            <div className="hidden md:flex justify-center text-slate-300">
              <ArrowRight className="w-5 h-5" />
            </div>

            {/* Step 3 */}
            <div className="p-3 rounded-xl border border-purple-200 bg-purple-50/40">
              <div className="w-7 h-7 rounded-lg bg-purple-600 text-white flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                3
              </div>
              <p className="text-xs font-bold text-slate-800">Cross-Encoder</p>
              <p className="text-[10px] text-slate-500 mt-0.5">ms-marco-MiniLM</p>
            </div>

            <div className="hidden md:flex justify-center text-slate-300">
              <ArrowRight className="w-5 h-5" />
            </div>

            {/* Step 4 */}
            <div className="p-3 rounded-xl border border-emerald-200 bg-emerald-50/40">
              <div className="w-7 h-7 rounded-lg bg-emerald-600 text-white flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                4
              </div>
              <p className="text-xs font-bold text-slate-800">Bounded Tools</p>
              <p className="text-[10px] text-slate-500 mt-0.5">RBAC & IDOR Validated</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-center text-center mt-3 pt-3 border-t border-slate-100">
            {/* Step 5 */}
            <div className="p-3 rounded-xl border border-indigo-200 bg-indigo-50/40">
              <div className="w-7 h-7 rounded-lg bg-indigo-600 text-white flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                5
              </div>
              <p className="text-xs font-bold text-slate-800">Grounded Synthesis</p>
              <p className="text-[10px] text-slate-500 mt-0.5">Groq Llama 3.3 70B</p>
            </div>

            <div className="hidden md:flex justify-center text-slate-300">
              <ArrowRight className="w-5 h-5" />
            </div>

            {/* Step 6 */}
            <div className="p-3 rounded-xl border border-amber-200 bg-amber-50/40">
              <div className="w-7 h-7 rounded-lg bg-amber-600 text-white flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                6
              </div>
              <p className="text-xs font-bold text-slate-800">Safety Guardrails</p>
              <p className="text-[10px] text-slate-500 mt-0.5">Confidence & Legal Check</p>
            </div>

            <div className="hidden md:flex justify-center text-slate-300">
              <ArrowRight className="w-5 h-5" />
            </div>

            {/* Step 7 */}
            <div className="p-3 rounded-xl border border-teal-200 bg-teal-50/40">
              <div className="w-7 h-7 rounded-lg bg-teal-600 text-white flex items-center justify-center mx-auto mb-1.5 font-bold text-xs">
                7
              </div>
              <p className="text-xs font-bold text-slate-800">Delivery / HITL</p>
              <p className="text-[10px] text-slate-500 mt-0.5">Agent Review if Flagged</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Deep-Dive Component Architecture */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Card 1: Retrieval & RAG */}
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Search className="w-4 h-4 text-brand-600" />
              Multi-Stage Retrieval & RAG Engine
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-slate-600">
            <p>
              <strong className="text-slate-800">Dense Vector Search:</strong> Embeddings generated via{" "}
              <code className="text-brand-600 font-mono">BAAI/bge-small-en-v1.5</code> (384 dimensions) indexed in PostgreSQL via <code className="text-brand-600 font-mono">pgvector</code> HNSW.
            </p>
            <p>
              <strong className="text-slate-800">Full-Text Search (FTS):</strong> PostgreSQL <code className="text-brand-600 font-mono">tsvector</code> with GIN indexing for exact keyword precision.
            </p>
            <p>
              <strong className="text-slate-800">Reciprocal Rank Fusion (RRF):</strong> Merges non-comparable vector distance and lexical rank scores mathematically ($k=60$).
            </p>
            <p>
              <strong className="text-slate-800">Cross-Encoder Reranking:</strong> Joint self-attention scoring with{" "}
              <code className="text-brand-600 font-mono">ms-marco-MiniLM-L-6-v2</code> eliminates false positives before LLM context assembly.
            </p>
          </CardContent>
        </Card>

        {/* Card 2: Bounded Tools & RBAC */}
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
              Bounded Tool Architecture & Security
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-slate-600">
            <p>
              <strong className="text-slate-800">Zero Direct Database Access:</strong> The LLM produces strict JSON tool call requests. It cannot generate raw SQL or invoke unapproved methods.
            </p>
            <p>
              <strong className="text-slate-800">Allowed Tool Registry:</strong> Only tools explicitly in <code className="text-emerald-700 font-mono">TOOL_REGISTRY</code> (<code className="text-emerald-700 font-mono">get_order_status</code>, <code className="text-emerald-700 font-mono">get_payment_status</code>) can execute.
            </p>
            <p>
              <strong className="text-slate-800">IDOR & Ownership Defense:</strong> Authorization is validated inside each tool using the authenticated user identity (<code className="text-emerald-700 font-mono">current_user</code>).
            </p>
            <p>
              <strong className="text-slate-800">Result Sanitization:</strong> Internal UUIDs, raw hashes, and unneeded columns are stripped before context injection.
            </p>
          </CardContent>
        </Card>

        {/* Card 3: Human-In-The-Loop Safety */}
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Bot className="w-4 h-4 text-amber-600" />
              Human-In-The-Loop & Guardrails
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-slate-600">
            <p>
              <strong className="text-slate-800">Deterministic Triggers:</strong> Escalations occur when confidence &lt; 0.70, context is missing, tools fail/deny, or legal keywords are detected.
            </p>
            <p>
              <strong className="text-slate-800">Pre-Delivery Review Queue:</strong> Flagged responses are held in <code className="text-amber-700 font-mono">human_reviews</code> until an agent approves, edits, or rejects them.
            </p>
            <p>
              <strong className="text-slate-800">Self-Approval Prohibition:</strong> The AI cannot approve or bypass review requirements on its own drafts.
            </p>
          </CardContent>
        </Card>

        {/* Card 4: Production Infrastructure */}
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Server className="w-4 h-4 text-indigo-600" />
              Production Infrastructure & Observability
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-slate-600">
            <p>
              <strong className="text-slate-800">PostgreSQL 16 + Redis 7:</strong> Containerized data storage with connection pooling, statement timeouts, and caching.
            </p>
            <p>
              <strong className="text-slate-800">Zero-Trust Network:</strong> Production Compose runs DB and Redis without published host ports.
            </p>
            <p>
              <strong className="text-slate-800">Observability & Tracing:</strong> In-memory metrics buffer tracking p50/p95/p99 HTTP latency, token consumption, and multi-span traces.
            </p>
            <p>
              <strong className="text-slate-800">CI/CD Automation:</strong> GitHub Actions automated matrix testing unit, API, security, migration, and Docker builds.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Documentation Links Footer */}
      <Card className="border-slate-200 bg-slate-50/70 p-5">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
              Official Architecture Documentation
            </h4>
            <p className="text-xs text-slate-500 mt-0.5">
              Read the full specifications, sequence diagrams, and Architecture Decision Records (ADRs).
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span className="font-mono text-slate-600">docs/architecture.md</span>
            <span className="font-mono text-slate-600">docs/demo-walkthrough.md</span>
            <span className="font-mono text-slate-600">docs/interview-walkthrough.md</span>
          </div>
        </div>
      </Card>
    </div>
  );
};
