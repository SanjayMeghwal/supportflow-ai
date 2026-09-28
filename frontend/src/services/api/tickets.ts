/**
 * SupportFlow AI — Tickets API Service
 *
 * Backend endpoints:
 *   POST  /api/v1/tickets                     — create ticket (CUSTOMER)
 *   GET   /api/v1/tickets                     — list tickets (role-scoped)
 *   GET   /api/v1/tickets/{id}                — ticket detail with messages
 *   PATCH /api/v1/tickets/{id}                — update metadata (AGENT/ADMIN)
 *   POST  /api/v1/tickets/{id}/messages       — add message
 *   GET   /api/v1/tickets/{id}/messages       — list messages
 *   POST  /api/v1/tickets/{id}/assign         — assign agent (AGENT/ADMIN)
 *
 * NOTE: There is NO separate /status endpoint. Status transitions are made
 * via PATCH /api/v1/tickets/{id} with { status: "NEW_STATUS" } in the body.
 */

import { apiClient } from "./client";
import {
  Ticket,
  TicketCreatePayload,
  TicketFilterParams,
  TicketListResponse,
  TicketMessage,
  TicketMessageCreatePayload,
  TicketUpdatePayload,
} from "@/types";

export const ticketsApi = {
  listTickets: async (params?: TicketFilterParams): Promise<TicketListResponse> => {
    const query = new URLSearchParams();
    if (params?.offset !== undefined) query.set("offset", params.offset.toString());
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    if (params?.status) query.set("status", params.status);
    if (params?.category) query.set("category", params.category);
    if (params?.priority) query.set("priority", params.priority);

    const queryString = query.toString();
    const endpoint = queryString ? `/api/v1/tickets?${queryString}` : "/api/v1/tickets";
    return apiClient.get<TicketListResponse>(endpoint);
  },

  getTicket: async (ticketId: string): Promise<Ticket> => {
    return apiClient.get<Ticket>(`/api/v1/tickets/${ticketId}`);
  },

  createTicket: async (payload: TicketCreatePayload): Promise<Ticket> => {
    return apiClient.post<Ticket>("/api/v1/tickets", payload);
  },

  /**
   * Update ticket metadata (status, priority, category, resolution_summary).
   * Status transitions are validated server-side against the lifecycle allowlist.
   * Use this for both metadata updates and status transitions.
   */
  updateTicket: async (ticketId: string, payload: TicketUpdatePayload): Promise<Ticket> => {
    return apiClient.patch<Ticket>(`/api/v1/tickets/${ticketId}`, payload);
  },

  addMessage: async (
    ticketId: string,
    payload: TicketMessageCreatePayload
  ): Promise<TicketMessage> => {
    return apiClient.post<TicketMessage>(`/api/v1/tickets/${ticketId}/messages`, payload);
  },

  listMessages: async (ticketId: string): Promise<TicketMessage[]> => {
    return apiClient.get<TicketMessage[]>(`/api/v1/tickets/${ticketId}/messages`);
  },

  assignTicket: async (ticketId: string, agentId: string): Promise<Ticket> => {
    return apiClient.post<Ticket>(`/api/v1/tickets/${ticketId}/assign`, { agent_id: agentId });
  },
};
