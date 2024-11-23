import discord
import os
import sqlite3
import datetime
from discord.ext import commands, tasks
from dotenv import load_dotenv

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@tasks.loop(hours=24)
async def renewal_reminder():
    try:
        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        today = datetime.now().date()
        threshold_date = today + datetime.timedelta(days=14)

        cursor.execute("""
            SELECT user_id, username, end_date FROM users
            WHERE DATE(end_date) = DATE(?) AND reminded = 0             
        """, (threshold_date,))

        users = cursor.fetchall()
        if not users:
            conn.close()
            return

        grouped_users = {}
        for user_id, username, end_date in users:
            if end_date not in grouped_users:
                grouped_users[end_date] = []
            grouped_users[end_date].append((user_id, username))

        channel = discord.utils.get(bot.get_all_channels(), name="general")
        if not channel:
            print("General channel not found.")
            conn.close()
            return

        for end_date, user_list in grouped_users.items():
            mentions = ", ".join(f"<@{user_id}>" for user_id, _ in user_list)
            await channel.send(
                f"{mentions}, your subscriptions are ending on {end_date}. "
                "Renew your subscription with `!renew <duration>` or cancel with `!remove <name>`."
            )

            for user_id, _ in user_list:
                cursor.execute(
                    "UPDATE users SET reminded = 1, paid = 0 WHERE user_id = ?", (user_id,))

                member = await bot.fetch_user(user_id)
                guild_member = discord.utils.get(
                    channel.guild.members, id=member.id)
                if guild_member:
                    await assign_role(guild_member, paid=0)

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error in renewal_reminder: {e}")


@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")


@bot.command
async def add_user(ctx, name: str, start_date: str, duration: int, mention: discord.Member = None):
    """
    Adds a user to the subscription list, resolving ambiguity with an optional mention.
    """
    try:
        matches = [m for m in ctx.guild.members if m.display_name == name]

        if len(matches) == 0:
            await ctx.send(f"No user found with the name '{name}'.")
            return

        if len(matches) == 1:
            member = matches[0]

        elif len(matches) > 1:
            if mention:
                member = mention
                if member not in matches:
                    await ctx.send(f"The user {mention} does not match the provided display name '{name}'.")
                    return
            else:
                await ctx.send(
                    f"Multiple users found with the name '{
                        name}'. Please specify a mention to clarify addition."
                )
                return

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = start + datetime.timedelta(days=30 * duration)

        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        cursor.execute("SELECT monthly_cost FROM plan_cost WHERE id = 1")
        result = cursor.fetchone()
        if not result:
            await ctx.send("Monthly cost is not set. Use `!set_monthly_cost` to define it.")
            return

        monthly_cost = result[0] / 6
        total_cost = monthly_cost * duration

        cursor.execute("SELECT * FROM users WHERE user_id = ?", (member.id,))
        if cursor.fetchone():
            await ctx.send(f"User '{member.display_name}' is already subscribed.")
            return

        cursor.execute("""
            INSERT INTO users (user_id, username, start_date, end_date, duration, cost, paid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (member.id, member.name, start_date, end.strftime("%Y-%m-%d"), duration, total_cost, 1))
        conn.commit()
        conn.close()

        await assign_role(member, paid=1)

        await ctx.send(
            f"User '{member.display_name}' has been added with a subscription ending on {
                end.strftime('%Y-%m-%d')}."
        )
    except ValueError:
        await ctx.send("Invalid date format. Please use YYYY-MM-DD.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")


@bot.command()
async def remove(ctx, name: str, mention: discord.Member = None):
    try:
        matches = [m for m in ctx.guild.members if m.display_name == name]

        # Case 1: No matches
        if len(matches) == 0:
            await ctx.send(f"No user found with the name '{name}'.")
            return

        # Case 2: One match
        if len(matches) == 1:
            member = matches[0]

            # Case 3: Multiple matches
        elif len(matches) > 1:
            if mention:
                # Use the mention parameter to resolve ambiguity
                member = mention
                if member not in matches:
                    await ctx.send(f"The user {mention} does not match the provided display name '{name}'.")
                    return
            else:
                # Notify the caller and stop if no mention is provided
                await ctx.send(
                    f"Multiple users found with the name '{
                        name}'. Please specify a mention to clarify removal."
                )
                return
        # Connect to the database
        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM user WHERE user_id = ?", (member.id,))
        if cursor.fetchone():
            # Delete user from database
            cursor.execute("DELETE FROM users WHERE user_id = ?", (member.id,))
            conn.commit()
            conn.close()

            await ctx.send(f"User '{member.display_name}' has been removed from the family plan.")
        else:
            await ctx.send(f"User '{member.display_name}' has failed to be removed.")
            conn.close()
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")


@bot.command()
async def list(ctx):
    try:
        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT username, start_date, end_date, duration, paid FROM user")
        users = cursor.fetchall()
        conn.close()

        if not users:
            await ctx.send("There are currently no users in the database.")
            return

        response = "***Spotify Family Plan Members***\n"
        for user in users:
            username, start_date, end_date, duration, paid = user
            status = "Paid" if paid else "Unpaid"
            response += (
                f"{username}\n"
                f"  - Start Date: {start_date}\n"
                f"  - End Date: {end_date}\n"
                f"  - Duration: {duration} months\n"
                f"  - Status: {status}\n"
            )
        await ctx.send(response)
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")


@bot.command()
async def myself(ctx):
    print(f"{ctx.author.name} requested the myself command.")
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT start_date, end_date, duration, paid FROM user WHERE user_id = ?", (ctx.author.id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        start_date, end_date, duration, paid = user
        status = "Paid" if paid else "Unpaid"
        response = f"{ctx.author.name} Information"
        response += (
            f"  - Start Date: {start_date}\n"
            f"  - End Date: {end_date}\n"
            f"  - Duration: {duration} months\n"
            f"  - Status: {status}\n"
        )
    else:
        await ctx.send("You are not registered in the database.")
        return


@bot.command()
async def set_cost(ctx, new_cost: float, effective_date: str = None):
    try:
        if ctx.author != ctx.guild.owner:
            await ctx.send("Only the server owner can update the cost.")
            return
        if not effective_date:
            today = datetime.now()
            effective_date = datetime(
                today.year, today.month, 1).strftime("%Y-%m-%d")
        else:
            try:
                effective_date = datetime.strptime(
                    effective_date, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                await ctx.send("Invalid date format. Please use YYYY-MM-DD.")
                return

        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        cursor.execute("SELECT monthly_cost FROM plan_cost WHERE id = 1")
        current_cost = cursor.fetchone()[0]

        cursor.execute(
            """
            UPDATE plan_cost SET monthly_cost = ?, effective_date = ? WHERE id = 1
            """, (new_cost, effective_date))

        cursor.execute(
            "SELECT user_id, username, end_date, duration FROM users")
        users = cursor.fetchall()

        for user_id, username, end_date, duration in users:
            end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
            if end_date_dt < effective_date_dt:
                # No adjustment needed for users whose subscriptions end before the effective date
                continue

        adjustments = []
        effective_date_dt = datetime.strptime(effective_date, "%Y-%m-%d")

        # Calculate remaining months from the effective date
        remaining_months = (end_date_dt.year - effective_date_dt.year) * \
            12 + (end_date_dt.month - effective_date_dt.month)

        # Calculate price difference
        old_total = current_cost * remaining_months
        new_total = new_cost * remaining_months
        adjustment = new_total - old_total

        # Update the user's cost in the database
        cursor.execute("""
                UPDATE users
                SET cost = ?
                WHERE user_id = ?
            """, (new_total, user_id))

        # Append adjustment details
        adjustments.append((user_id, username, adjustment))

        conn.commit()

        if adjustments:
            response = "**Price Adjustment Summary:**\n"
            for user_id, username, adjustment in adjustments:
                if adjustment > 0:
                    response += f"- {username} (<@{user_id}>) owes **${
                        adjustment:.2f}**.\n"
                elif adjustment < 0:
                    response += f"- {
                        username} (<@{user_id}>) is owed a refund of **${-adjustment:.2f}**.\n"
                else:
                    response += f"- {username} (<@{user_id}>) has no adjustment.\n"
            await ctx.send(response)
        else:
            await ctx.send("No adjustments are needed for current users.")

        conn.close()
        await ctx.send(f"The monthly cost of the family plan has been updated to ${new_cost:.2f}.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")


@bot.command()
async def get_cost(ctx):
    """
    Displays the current monthly cost of the family plan.
    """
    try:
        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        cursor.execute("SELECT monthly_cost FROM plan_cost WHERE id = 1")
        result = cursor.fetchone()
        conn.close()

        if not result:
            await ctx.send("The monthly cost has not been set.")
            return

        monthly_cost = result[0]
        await ctx.send(f"The current monthly cost of the family plan is ${monthly_cost:.2f}.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")


@ bot.command()
async def renew(ctx, *args):
    try:
        if len(args) == 1:
            duration = int(args[0])
            user_id = ctx.author.id
            user_name = ctx.author.display_name
        elif len(args) == 2:
            if ctx.author != ctx.guild.owner:
                await ctx.send("Only the server owner can renew for other members. If this is for yourself, use '!renew <duration>'.")
                return
            user_name = args[0]
            duration = int(args[1])
            matches = [
                m for m in ctx.guild.members if m.display_name == user_name]
            if len(matches) == 0:
                await ctx.send(f"No user found with the name '{user_name}'.")
                return
            elif len(matches) > 1:
                await ctx.send(f"Multiple users found with the name '{user_name}'.")
                return
            member = matches[0]
            user_id = member.id
            user_name = member.display_name
        else:
            await ctx.send(f"Invalid parameters. Use '!renew <duration>' or '!renew <name> <duration>'.")
            return
        conn = sqlite3.connect("data.db")
        cursor = conn.cursor()

        cursor.execute("SELECT monthly_cost FROM plan_cost WHERE id = 1")
        result = cursor.fetchone()
        if not result:
            await ctx.send("Monthly cost is not set. Use `!set_monthly_cost` to define it.")
            return

        monthly_cost = result[0]
        total_cost = monthly_cost * duration

        cursor.execute(
            "SELECT end_date FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            await ctx.send(f"User '{user_name}' is not in the subscription list.")
            return

        current_end_date = datetime.strptime(user[0], "%Y-%m-%d")
        new_end_date = current_end_date + \
            datetime.timedelta(days=30 * duration)

        cursor.execute("""
            UPDATE users
            SET end_date = ?, duration = ?, cost = ?, paid = 1
            WHERE user_id = ?
        """, (new_end_date.strftime("%Y-%m-%d"), duration, total_cost, user_id))
        conn.commit()
        conn.close()

        await assign_role(member, paid=1)

        await ctx.send(
            f"Subscription for '{user_name}' has been renewed for {
                duration} month(s), costing ${total_cost:.2f}. "
            f"New end date: {new_end_date.strftime('%Y-%m-%d')}."
        )
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")


async def assign_role(member, paid):
    """
    Assigns the 'Paid' or 'Unpaid' role to the member based on the paid status.
    - Creates roles if they don't exist.
    """
    guild = member.guild

    # Define role names
    paid_role_name = "Paid"
    unpaid_role_name = "Not Paid"

    # Find roles in the server
    paid_role = discord.utils.get(guild.roles, name=paid_role_name)
    unpaid_role = discord.utils.get(guild.roles, name=unpaid_role_name)

    # Create roles if they don't exist
    if not paid_role:
        paid_role = await guild.create_role(name=paid_role_name, color=discord.Color.green())
    if not unpaid_role:
        unpaid_role = await guild.create_role(name=unpaid_role_name, color=discord.Color.red())

    # Assign the correct role
    if paid == 1:
        await member.add_roles(paid_role)
        await member.remove_roles(unpaid_role)
    else:
        await member.add_roles(unpaid_role)
        await member.remove_roles(paid_role)


@bot.command()
async def help(ctx):
    print(f"{ctx.author.name} requested the help command.")
    help_message = (
        "***Spotify Payment Automated Bot Commands***\n\n"
        "Available commands are shown below: \n"
        "!add - \n"
        "!remove - \n"
        "!list - \n"
        "!myself - \n"
        "!set_cost - \n"
        "!get_cost - \n"
        "!renew - \n"
        f"\nTag @{ctx.guild.owner.name} if you still require help."
    )
    await ctx.send(help_message)


@bot.event
async def on_message(message):
    await bot.process_commands(message)

# Need a way to calculate owed_cost when price updates (more expensive) or price decreases

# Run bot
load_dotenv(
    dotenv_path="C:/Users/chenw/Discord_Bots/Family_Plan_Auto/fpa.env")
token = os.getenv("DISCORD_TOKEN")
bot.run(token)
