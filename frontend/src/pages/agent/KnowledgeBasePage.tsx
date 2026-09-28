/**
 * Knowledge Base Page — /agent/knowledge
 * Browse and search ingested knowledge documents and test hybrid RAG search.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { knowledgeApi } from "@/services/api";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  Button,
  Input,
  Alert,
  EmptyState,
  Spinner,
} from "@/components/ui";
import { PageHeader } from "@/components/layout/PageHeader";
import { KnowledgeDocument } from "@/types";
import { BookOpen, Search, Database, Calendar, Hash } from "lucide-react";

export const KnowledgeBasePage: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [isSearchMode, setIsSearchMode] = useState(false);

  // List documents query
  const {
    data: docsData,
    isLoading: docsLoading,
    isError: docsError,
  } = useQuery({
    queryKey: ["knowledge", "documents"],
    queryFn: () => knowledgeApi.listDocuments({ limit: 30, offset: 0 }),
    enabled: !isSearchMode,
  });

  // Search query — only fires when user submits a search
  const {
    data: searchData,
    isLoading: searchLoading,
    isError: searchError,
    isFetching: searchFetching,
  } = useQuery({
    queryKey: ["knowledge", "search", submittedQuery],
    queryFn: () => knowledgeApi.search(submittedQuery, "hybrid", 10),
    enabled: isSearchMode && !!submittedQuery,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    setSubmittedQuery(q);
    setIsSearchMode(true);
  };

  const handleClear = () => {
    setSearchQuery("");
    setSubmittedQuery("");
    setIsSearchMode(false);
  };

  const isLoading = isSearchMode ? (searchLoading || searchFetching) : docsLoading;
  const isError = isSearchMode ? searchError : docsError;

  return (
    <div className="px-6 py-8 max-w-5xl mx-auto">
      <PageHeader
        title="Knowledge Base"
        description="Browse ingested documents or run hybrid semantic search across the knowledge index."
      />

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <div className="flex-1">
          <Input
            id="kb-search-input"
            type="search"
            placeholder="Search knowledge base… (e.g. refund policy, billing)"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              if (!e.target.value) handleClear();
            }}
            leftIcon={<Search className="w-4 h-4" />}
          />
        </div>
        <Button id="kb-search-submit" type="submit" variant="outline" disabled={!searchQuery.trim()}>
          Search
        </Button>
        {isSearchMode && (
          <Button id="kb-clear" type="button" variant="ghost" onClick={handleClear}>
            Clear
          </Button>
        )}
      </form>

      {isError && (
        <Alert variant="error" className="mb-4">
          {isSearchMode
            ? "Failed to search knowledge base."
            : "Failed to load knowledge documents."}
        </Alert>
      )}

      {/* Search results */}
      {isSearchMode ? (
        <>
          {isLoading ? (
            <div className="flex justify-center py-16">
              <Spinner size="lg" className="text-brand-600" />
            </div>
          ) : !searchData?.results?.length ? (
            <EmptyState
              icon={<Search className="w-7 h-7" />}
              title="No results found"
              description={`No knowledge chunks matched "${submittedQuery}". Try different keywords.`}
            />
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-slate-400">
                {searchData.total_results} results · search type: {searchData.search_type}
              </p>
              {searchData.results.map((result, idx) => (
                <Card key={result.chunk_id} className="animate-in">
                  <CardHeader>
                    <CardTitle className="text-sm flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-brand-50 text-brand-600 flex items-center justify-center text-[10px] font-bold shrink-0">
                        {idx + 1}
                      </span>
                      {result.document_title}
                    </CardTitle>
                    <div className="flex items-center gap-2 flex-wrap">
                      {result.score != null && (
                        <Badge variant="secondary" size="sm">
                          Score: {result.score.toFixed(3)}
                        </Badge>
                      )}
                      {result.rerank_score != null && (
                        <Badge variant="brand" size="sm">
                          Reranked: {result.rerank_score.toFixed(3)}
                        </Badge>
                      )}
                      <Badge variant="outline" size="sm" className="font-mono">
                        chunk #{result.chunk_index}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-slate-700 whitespace-pre-wrap line-clamp-3">
                      {result.content}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </>
      ) : (
        /* Document list */
        <>
          {docsLoading ? (
            <div className="flex justify-center py-16">
              <Spinner size="lg" className="text-brand-600" />
            </div>
          ) : !docsData?.documents?.length ? (
            <EmptyState
              icon={<BookOpen className="w-7 h-7" />}
              title="No documents ingested"
              description="Knowledge base documents will appear here once uploaded and processed."
            />
          ) : (
            <>
              <p className="text-xs text-slate-400 mb-3">
                {docsData.total} document{docsData.total !== 1 ? "s" : ""} in the knowledge base
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {docsData.documents.map((doc: KnowledgeDocument) => (
                  <Card key={doc.id} className="hover:shadow-md transition-shadow animate-in">
                    <CardHeader>
                      <CardTitle className="text-sm line-clamp-2">
                        {doc.title}
                      </CardTitle>
                      <Badge
                        variant={doc.is_active ? "success" : "secondary"}
                        size="sm"
                      >
                        {doc.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </CardHeader>
                    <CardContent>
                      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
                        <span className="flex items-center gap-1">
                          <Database className="w-3 h-3" />
                          {doc.source_type}
                        </span>
                        <span className="flex items-center gap-1">
                          <Hash className="w-3 h-3" />
                          {doc.chunk_count} chunk{doc.chunk_count !== 1 ? "s" : ""}
                        </span>
                        <span className="flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          {new Date(doc.created_at).toLocaleDateString("en-US", {
                            year: "numeric",
                            month: "short",
                            day: "numeric",
                          })}
                        </span>
                      </div>
                      {doc.source_uri && (
                        <p className="text-xs text-slate-400 mt-2 font-mono truncate">
                          {doc.source_uri}
                        </p>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
};
