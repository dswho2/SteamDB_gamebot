import discord
from discord.ext import commands, tasks
import asyncio
from dotenv import load_dotenv
import os
import logging
import aiohttp
import json
from datetime import datetime, timezone

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
TARGET_ROLE_NAME = 'Free Games'
CHANNEL_ID = int(os.getenv('bot_channel'))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

previous_games = set()

class SteamAPI:
    def __init__(self):
        self.session = None
        self.store_url = "https://store.steampowered.com"
        
    async def ensure_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def get_featured_free_games(self):
        """Get games that are currently free (100% discounted) from featured section"""
        await self.ensure_session()
        free_games = []
        
        try:
            async with self.session.get(f"{self.store_url}/api/featuredcategories") as response:
                if response.status == 200:
                    data = await response.json()
                    specials = data.get('specials', {}).get('items', [])
                    
                    for game in specials:
                        # Check if the game is 100% discounted
                        if game.get('discount_percent') == 100:
                            free_games.append({
                                'name': game.get('name'),
                                'image_url': game.get('large_capsule_image'),
                                'status': 'Free to Keep!',
                                'store_url': f"{self.store_url}/app/{game.get('id')}",
                                'original_price': game.get('original_price', 0) / 100 if game.get('original_price') else 0,
                                'discount_end': game.get('discount_expiration', 0)
                            })
        
        except Exception as e:
            logger.error(f"Error fetching featured free games: {e}")
        
        return free_games

    async def get_special_free_games(self):
        """Get all current special offers that are 100% off"""
        await self.ensure_session()
        free_games = []
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Use the specials page instead of the search API
            async with self.session.get(f"{self.store_url}/specials", headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    # Look for games with 100% discount in the response
                    # You might need to adjust this based on the actual HTML structure
                    if "-100%" in text:
                        # Process the page content to find free games
                        # This is a simplified example; you might need to use better parsing
                        pass
                        
        except Exception as e:
            logger.error(f"Error fetching special free games: {e}")
        
        return free_games

    async def get_all_free_games(self):
        """Combine all methods to get free games"""
        free_games = []
        
        # Get featured free games
        featured_games = await self.get_featured_free_games()
        if featured_games:
            free_games.extend(featured_games)
        
        # Remove duplicates based on name
        seen = set()
        unique_games = []
        for game in free_games:
            if game['name'] not in seen:
                seen.add(game['name'])
                unique_games.append(game)

        logger.info(f"Total unique free games found: {len(unique_games)}")
        for game in unique_games:
            logger.info(f"Found free game: {game['name']} - {game['status']}")
        
        return unique_games

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    await bot.tree.sync()
    await ensure_role_exists(bot.guilds[0])
    await check_free_games()
    check_free_games.start()

async def ensure_role_exists(guild: discord.Guild):
    role = discord.utils.get(guild.roles, name=TARGET_ROLE_NAME)
    if role is None:
        logger.info(f"Creating '{TARGET_ROLE_NAME}' role...")
        await guild.create_role(name=TARGET_ROLE_NAME, mentionable=True)
    else:
        logger.info(f"'{TARGET_ROLE_NAME}' role already exists")

@tasks.loop(minutes=30)
async def check_free_games():
    logger.info("Checking for new free games...")
    
    steam_api = SteamAPI()
    games = await steam_api.get_all_free_games()
    await steam_api.close()
    
    if games is None:
        logger.error("Failed to fetch games")
        return
        
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Could not find channel with ID {CHANNEL_ID}")
        return
        
    role = discord.utils.get(channel.guild.roles, name=TARGET_ROLE_NAME)
    if not role:
        logger.error(f"Could not find role {TARGET_ROLE_NAME}")
        return
    
    current_games = {f"{game['name']} - {game['status']}" for game in games}
    new_games = [game for game in games if f"{game['name']} - {game['status']}" not in previous_games]
    
    logger.info(f"Current free games: {current_games}")
    logger.info(f"New games detected: {[game['name'] for game in new_games]}")
    
    for game in new_games:
        try:
            embed = discord.Embed(
                title=game['name'],
                description=f"{game['status']}\nOriginal Price: ${game.get('original_price', 0):.2f}",
                url=game['store_url'],
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=game['image_url'])
            
            # Add discount end time if available
            if game.get('discount_end'):
                end_time = datetime.fromtimestamp(game['discount_end'], tz=timezone.utc)
                embed.add_field(name="Offer Ends", value=end_time.strftime("%Y-%m-%d %H:%M UTC"), inline=False)
            
            embed.add_field(name="Store Page", value=f"[Click here]({game['store_url']})", inline=False)
            await channel.send(f"Hey {role.mention}, a new free game is available!", embed=embed)
            logger.info(f"Notified about new game: {game['name']}")
        except Exception as e:
            logger.error(f"Error sending notification for {game['name']}: {e}")
    
    previous_games.clear()
    previous_games.update(current_games)

@bot.tree.command(name="joinfreegames", description="Assign the 'Free Games' role to the user")
async def assign_role(interaction: discord.Interaction):
    role = discord.utils.get(interaction.guild.roles, name=TARGET_ROLE_NAME)
    
    if role in interaction.user.roles:
        await interaction.response.send_message(f"You already have the {TARGET_ROLE_NAME} role!")
    else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"{interaction.user.mention} you have been assigned the {TARGET_ROLE_NAME} role!")
        logger.info(f"Assigned {TARGET_ROLE_NAME} role to {interaction.user}")

@bot.tree.command(name="checkfreegames", description="Manually check for free games")
async def manual_check(interaction: discord.Interaction):
    await interaction.response.send_message("Manually checking for free games...")
    await check_free_games()

if __name__ == "__main__":
    bot.run(TOKEN)