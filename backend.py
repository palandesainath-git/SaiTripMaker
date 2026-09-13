import os
import certifi
from dotenv import load_dotenv

import uuid
import asyncio
import operator
from typing import TypedDict, Annotated

import psycopg_pool
from psycopg.rows import dict_row

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, SystemMessage
from langchain_groq import ChatGroq

from mcp_client import tavily_mcp_search, aviation_mcp_call, extract_destination, forecast_mcp_search, weather_mcp_search

# =========================
# Environment Setup
# =========================
load_dotenv()
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

def get_database_url():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing. Please add it to your .env")
    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return database_url

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")

# =========================
# LLM
# =========================
llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

# =========================
# State
# =========================
class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: int
    weather_results: str

# =========================
# Flight Agent
# =========================
async def flight_agent(state: TravelState):
    query = state["user_query"]
    try:
        airports = await aviation_mcp_call("list_airports")
        airlines = await aviation_mcp_call("list_airlines")

        prompt = f"""
        You are a travel flight expert.
        User Query: {query}
        Airport Data: {airports}
        Airline Data: {airlines}
        """

        response = llm.invoke([
            SystemMessage(content="You are an expert travel flight planner."),
            HumanMessage(content=prompt)
        ])
        flight_data = response.content
    except Exception as e:
        flight_data = f"Flight information unavailable: {str(e)}"

    return {
        "flight_results": flight_data,
        "messages": [AIMessage(content="Flight recommendations generated")],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# =========================
# Hotel Agent
# =========================
async def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    hotel_results = await tavily_mcp_search(query)
    return {
        "hotel_results": hotel_results,
        "messages": [AIMessage(content="Hotel information fetched.")],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# =========================
# Weather Agent
# =========================
async def weather_agent(state: TravelState):
    city = extract_destination(state["user_query"])
    weather_data = await weather_mcp_search(city)
    forecast_data = await forecast_mcp_search(city)
    return {
        "weather_results": f"Current Weather:\n{weather_data}\nForecast:\n{forecast_data}",
        "messages": [AIMessage(content="Weather information fetched")]
    }

# =========================
# Itinerary Agent
# =========================
async def itinerary_agent(state: TravelState):
    prompt = f"""
    Create a complete travel itinerary.
    User Query: {state['user_query']}
    Flight Results: {state['flight_results']}
    Hotel Results: {state['hotel_results']}
    Weather Results: {state['weather_results']}
    """
    response = llm.invoke([
        SystemMessage(content="You are an expert travel planner."),
        HumanMessage(content=prompt)
    ])
    return {
        "itinerary": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# =========================
# Final Agent
# =========================
async def final_agent(state: TravelState):
    final_prompt = f"""
    Generate the final travel response for the user.
    User Request: {state['user_query']}
    Flights: {state['flight_results']}
    Hotels: {state['hotel_results']}
    Weather: {state['weather_results']}
    Itinerary: {state['itinerary']}
    """
    response = llm.invoke([
        SystemMessage(content="You are a professional AI travel booking assistant."),
        HumanMessage(content=final_prompt)
    ])
    return {"messages": [response], "llm_calls": state.get("llm_calls", 0) + 1}

# =========================
# Graph Build
# =========================
graph = StateGraph(TravelState)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "flight_agent")
graph.add_edge("flight_agent", "hotel_agent")
graph.add_edge("hotel_agent", "weather_agent")
graph.add_edge("weather_agent", "itinerary_agent")
graph.add_edge("itinerary_agent", "final_agent")
graph.add_edge("final_agent", END)

# =========================
# PostgreSQL Pool + Checkpointer
# =========================
DATABASE_URL = get_database_url()
pool = psycopg_pool.ConnectionPool(conninfo=DATABASE_URL, row_factory=dict_row)
with pool.connection() as conn:
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)

# =========================
# Function for FastAPI
# =========================
def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )
    final_answer = result["messages"][-1].content
    return {
        "thread_id": thread_id,
        "answer": final_answer,
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "itinerary": result.get("itinerary", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


