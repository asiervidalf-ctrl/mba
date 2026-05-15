from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mesa import Agent

if TYPE_CHECKING:
    from model_fantasy import ManagerAgent, PlayerAgent


BONUS_BY_RANK = [6_000_000, 5_000_000, 4_000_000, 3_000_000, 2_000_000, 1_000_000]
DAILY_MARKET_SIZE = 6


@dataclass
class MarketListing:
    """Representa un jugador que sale al mercado en una jornada concreta."""

    listing_id: str
    round_number: int
    player: "PlayerAgent"
    ask_price: int
    source: str
    seller: "ManagerAgent | None" = None


class MarketAgent(Agent):
    """Agente que gestiona el mercado diario y las bonificaciones de jornada."""

    def __init__(self, model: Any, daily_market_size: int = DAILY_MARKET_SIZE) -> None:
        """Prepara contenedores de mercado diario, historico de subastas y bonus."""
        super().__init__(model)
        self.daily_market_size = daily_market_size
        self.auction_history: list[dict[str, Any]] = []
        self.bonus_history: list[dict[str, Any]] = []
        self.daily_history: list[dict[str, Any]] = []
        self.last_open_listings: list[MarketListing] = []
        self.remaining_open_listings: list[MarketListing] = []
        self.last_completed_sales: list[dict[str, Any]] = []
        self.last_round_market_days: list[dict[str, Any]] = []
        self.last_bonus_total = 0

    def _build_listing(
        self,
        *,
        player: "PlayerAgent",
        source: str,
        seller: "ManagerAgent | None" = None,
    ) -> MarketListing:
        """Construye una ficha de mercado para un jugador concreto."""
        seller_name = seller.name if seller is not None else "market"
        listing_id = (
            f"{self.model.current_round}-"
            f"{self.model.current_market_day}-{source}-{seller_name}-{player.player_id}"
        )
        return MarketListing(
            listing_id=listing_id,
            round_number=self.model.current_round,
            player=player,
            ask_price=player.market_value,
            source=source,
            seller=seller,
        )

    def _serialize_listing(self, listing: MarketListing) -> dict[str, Any]:
        """Convierte una publicacion en un diccionario listo para guardar en JSON."""
        return {
            "listing_id": listing.listing_id,
            "round": listing.round_number,
            "market_day": self.model.current_market_day,
            "player": listing.player.name,
            "player_id": listing.player.player_id,
            "team": listing.player.team_name,
            "position": listing.player.position,
            "ask_price": listing.ask_price,
            "source": listing.source,
            "seller": listing.seller.name if listing.seller is not None else "market",
        }

    def _open_league_market(self) -> list[MarketListing]:
        """Abre solo el mercado oficial del dia con jugadores libres de la liga."""
        listings: list[MarketListing] = []
        free_players = list(self.model.available_players())
        if free_players:
            selection_size = min(self.daily_market_size, len(free_players))
            for player in self.model.random_state.sample(free_players, selection_size):
                listings.append(self._build_listing(player=player, source="market"))
        return listings

    def _build_manager_market_listings(
        self,
        sale_map: dict[int, list["PlayerAgent"]],
        reserved_ids: set[int] | None = None,
    ) -> list[MarketListing]:
        """Construye las fichas de mercado para los jugadores puestos en venta por managers."""
        listings: list[MarketListing] = []
        listed_player_ids = set(reserved_ids or set())
        for manager in self.model.manager_agents:
            for player in sale_map.get(manager.unique_id, []):
                if player.player_id in listed_player_ids:
                    continue
                listings.append(self._build_listing(player=player, source="manager", seller=manager))
                listed_player_ids.add(player.player_id)
        return listings

    def open_daily_market(self) -> list[MarketListing]:
        """Abre el mercado del dia tras una decision global diaria de todos los managers."""
        for manager in self.model.manager_agents:
            manager.remaining_market_purchase_capacity = 0

        league_listings = self._open_league_market()
        reserved_ids = {listing.player.player_id for listing in league_listings}

        provisional_sales: dict[int, list["PlayerAgent"]] = {}
        for manager in self.model.manager_agents:
            provisional_sales[manager.unique_id] = manager.propose_market_day_sales(league_listings)

        tentative_manager_listings = self._build_manager_market_listings(provisional_sales, reserved_ids)
        tentative_market = list(league_listings) + tentative_manager_listings

        final_sales: dict[int, list["PlayerAgent"]] = {}
        for manager in self.model.manager_agents:
            plan = manager.decide_market_day(tentative_market)
            selected_ids = list(plan.get("sale_player_ids", [])) if isinstance(plan, dict) else []
            squad_by_id = {player.player_id: player for player in manager.squad}
            final_sales[manager.unique_id] = [
                squad_by_id[player_id]
                for player_id in selected_ids
                if player_id in squad_by_id
            ]

        listings = list(league_listings) + self._build_manager_market_listings(final_sales, reserved_ids)
        self.model.random_state.shuffle(listings)
        self.last_open_listings = listings
        self.remaining_open_listings = list(listings)
        return listings

    def pending_sale_slots(self, manager: "ManagerAgent") -> int:
        """Cuenta cuantas ventas propias siguen abiertas en el mercado del dia."""
        return sum(
            1
            for listing in self.remaining_open_listings
            if listing.seller is not None and listing.seller.unique_id == manager.unique_id
        )

    def _collect_bids(self, listing: MarketListing) -> list[tuple["ManagerAgent", int]]:
        """Recoge las pujas validas de todos los managers para una publicacion."""
        bids: list[tuple["ManagerAgent", int]] = []
        for manager in self.model.manager_agents:
            if listing.seller is not None and manager.unique_id == listing.seller.unique_id:
                continue
            bid = manager.planned_bid_for_listing(listing)
            if bid is not None and bid >= listing.ask_price:
                bids.append((manager, bid))
        return bids

    def _resolve_listing(self, listing: MarketListing) -> dict[str, Any]:
        """Resuelve una publicacion concreta: venta, compra o retirada por el mercado."""
        bids = self._collect_bids(listing)
        player = listing.player

        result: dict[str, Any] = {
            "round": self.model.current_round,
            "market_day": self.model.current_market_day,
            "player": player.name,
            "player_id": player.player_id,
            "source": listing.source,
            "seller": listing.seller.name if listing.seller is not None else "market",
            "ask_price": listing.ask_price,
            "status": "unsold",
        }

        if bids:
            bids.sort(key=lambda item: item[1], reverse=True)
            highest_bid = bids[0][1]
            top_bidders = [item for item in bids if item[1] == highest_bid]
            winner, winning_bid = self.model.random_state.choice(top_bidders)

            if listing.seller is None:
                self.model.purchase_player_from_market(winner, player, winning_bid)
            else:
                self.model.transfer_player_between_managers(listing.seller, winner, player, winning_bid)

            result.update(
                {
                    "status": "sold",
                    "buyer": winner.name,
                    "price": winning_bid,
                    "bids": [{"manager": manager.name, "bid": bid} for manager, bid in bids],
                }
            )
            return result

        if listing.seller is not None:
            self.model.sell_player_to_market(listing.seller, player, player.market_value)
            result.update({"status": "sold_to_market", "price": player.market_value})

        return result

    def run_market_day(self) -> list[dict[str, Any]]:
        """Ejecuta la sesion diaria de mercado completa y guarda su trazabilidad."""
        self.last_completed_sales = []
        listings = self.open_daily_market()
        for listing in listings:
            self.last_completed_sales.append(self._resolve_listing(listing))
            self.remaining_open_listings = [
                open_listing
                for open_listing in self.remaining_open_listings
                if open_listing.listing_id != listing.listing_id
            ]

        day_summary = {
            "round": self.model.current_round,
            "market_day": self.model.current_market_day,
            "listings": [self._serialize_listing(listing) for listing in listings],
            "sales": list(self.last_completed_sales),
        }
        self.daily_history.append(day_summary)
        self.auction_history.extend(self.last_completed_sales)
        return self.last_completed_sales

    def run_market_round(self, days_per_round: int) -> list[dict[str, Any]]:
        """Ejecuta todos los dias de mercado que ocurren antes de cerrar la jornada."""
        self.last_round_market_days = []
        for market_day in range(1, days_per_round + 1):
            self.model.current_market_day = market_day
            self.run_market_day()
            self.last_round_market_days.append(self.daily_history[-1])
        return self.last_round_market_days

    def distribute_round_bonuses(self) -> list[dict[str, Any]]:
        """Reparte bonificaciones economicas segun la clasificacion de la jornada."""
        ranking = sorted(
            self.model.manager_agents,
            key=lambda manager: (manager.points_round, manager.points_total),
            reverse=True,
        )

        payouts: list[dict[str, Any]] = []
        self.last_bonus_total = 0
        for index, manager in enumerate(ranking[: len(BONUS_BY_RANK)]):
            bonus = BONUS_BY_RANK[index]
            manager.cash += bonus
            bonus_entry = {
                "round": self.model.current_round,
                "market_day": self.model.current_market_day,
                "manager": manager.name,
                "rank": index + 1,
                "bonus": bonus,
                "points_round": round(manager.points_round, 2),
            }
            manager.bonus_history.append(bonus_entry)
            payouts.append(bonus_entry)
            self.last_bonus_total += bonus

        self.bonus_history.extend(payouts)
        return payouts
