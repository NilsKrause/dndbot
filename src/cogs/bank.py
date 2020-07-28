"""This is a cog for a discord.py bot.
It will add commands to manage a guild bank.
"""
# pylint: disable=E0402, E0211
from datetime import datetime, timezone
from discord.ext import commands
from discord.utils import get
from discord import Embed, Member
from .models.core import TransactionData
from .models.transaction_model import TransactionDB

CURRENCIES = ('platinum', 'gold', 'electrum', 'silver', 'copper')
CURRENCIES_SHORT = tuple(s[0] for s in CURRENCIES)


class Bank(commands.Cog, name='Bank'):
    def __init__(self, client):
        self.client = client
        try:
            self.emoji = {c: get(self.client.mainguild.emojis, name=c.lower())
                          or c for c in CURRENCIES}
        except (TypeError, AttributeError):
            self.emoji = None
        self.TransactionDB = TransactionDB(client)

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.emoji:
            self.emoji = {c: get(self.client.mainguild.emojis, name=c.lower())
                          or c for c in CURRENCIES}

    def is_admin():
        async def predicate(ctx):
            return ctx.bot.user_is_admin(ctx.author)
        return commands.check(predicate)

    def get_balance(self, account):
        coins = {c: 0 for c in CURRENCIES}
        with self.client.state.get_session() as session:
            for transaction in self.TransactionDB.query_all(
                receiver_id=account,
                confirmed=True
            ):
                for c in CURRENCIES:
                    coins[c] += getattr(transaction, c) or 0
        return coins

    async def print_balance(self, ctx, account):
        coins = self.get_balance(account)
        e = Embed()
        coins_string = [f'{v} {self.emoji[k]}' for k, v in coins.items()]
        e.add_field(name='Your Balance', value=' | '.join(coins_string))
        await ctx.send(embed=e)

    def format_transaction(self, transaction, show_receiver=False):
        coins = {
            c: getattr(transaction, c) if getattr(transaction, c) else 0 for c in CURRENCIES
        }
        date = transaction.date.split('.')[0].replace('T', ' ') + ' UTC'
        user = self.client.get_user(transaction.user_id)
        user_str = user.name + '#' + user.discriminator
        description = transaction.description
        transaction_id = transaction._id
        confirmed = transaction.confirmed
        title = f'{"(Pending) " * (not confirmed)}ID:{transaction_id} | {date} - {user_str}'
        body = [f'**{coins[c]}** {self.emoji[c]} ' if coins[c] else '' for c in CURRENCIES]
        if show_receiver:
            receiver = self.client.get_user(transaction.account_nr)
            body.append(f'\nAn: {receiver.name + "#" + receiver.discriminator}')
        body.append(f'\nZweck: {description}')

        return (title, ''.join(body))

    async def process_transaction(
        self, ctx, transaction_string, description, sender_id, receiver_id, confirm
    ):
        if not description or not transaction_string:
            await ctx.send('Please provide a transaction string and a description')
            return

        for c in transaction_string:
            if (c not in ',+-1234567890') and (c not in CURRENCIES_SHORT):
                await ctx.send('Invalid character in transaction ' + c)
                return

        transaction = self.TransactionDB.create_new(
            date=datetime.now(tz=timezone.utc).isoformat(),
            user_id=ctx.author.id,
            receiver_id=receiver_id,
            sender_id=sender_id,
            description=description,
            confirmed=confirm,
            platinum=None,
            electrum=None,
            gold=None,
            silver=None,
            copper=None
        )

        split = transaction_string.split(',')

        for coinstring in split:
            amount = int(coinstring[:-1])
            currency = coinstring[-1:]
            if currency not in CURRENCIES_SHORT:
                await ctx.send('Invalid currency detected:' + currency)
                return
            currency = CURRENCIES[CURRENCIES_SHORT.index(currency)]
            setattr(transaction, currency, amount)

        if sender_id != receiver_id:
            transaction2 = self.TransactionDB.create_new(
                date=datetime.now(tz=timezone.utc).isoformat(),
                user_id=ctx.author.id,
                receiver_id=sender_id,
                sender_id=sender_id,
                description=description,
                confirmed=confirm,
                platinum=None,
                electrum=None,
                gold=None,
                silver=None,
                copper=None
            )
            for currency in CURRENCIES:
                amount = getattr(transaction, currency)
                if amount:
                    setattr(transaction2, currency, amount*-1)
        e = Embed(
            title='Transaction added' + (' (pending confirmation)' * (not confirm)),
            description='\n'.join(self.format_transaction(transaction))
        )
        await ctx.send(embed=e)

    async def print_log(self, ctx, start, num, account_nr):
        e = Embed(title='Transaction Log')
        with self.client.state.get_session() as session:
            for transaction in reversed(
                session.query(TransactionData)
                    .filter_by(account_nr=account_nr)
                    .order_by(TransactionData._id.desc())
                    .limit(num+start)
                    .all()[start:num+start]
            ):
                title, body = self.format_transaction(transaction)
                e.add_field(inline=False, name=title, value=body)
        await ctx.send(embed=e)

    async def print_pending(self, ctx):
        e = Embed(title='Pending Transactions')
        with self.client.state.get_session() as session:
            for transaction in session.query(TransactionData).filter_by(confirmed=0).all():
                title, body = self.format_transaction(transaction, show_receiver=True)
                e.add_field(inline=False, name=title, value=body)
        await ctx.send(embed=e)

    @commands.group(
        name='bank',
        aliases=[],
        invoke_without_command=True,
    )
    @is_admin()
    async def bank(self, ctx):
        """View and control the bank account `+help bank`"""
        await self.print_balance(ctx, 0)

    @bank.command(
        name='add',
    )
    @is_admin()
    async def bank_add(self, ctx, transaction_string=None, *, description=None):
        """Add a transaction to the bank `+help bank add`

        The transaction_string is a comma separated list of amount and currency pairs.
        example `+bank 2g,5s Donation from Dora`
        example `+bank -2g,-5s Bought food for the kitchen`
        """
        await self.process_transaction(ctx, transaction_string, description, 0, confirm=True)

    @bank.command(
        name='history',
        aliases=['log'],
    )
    @is_admin()
    async def bank_history(self, ctx, start=0, num=10, member: Member = None):
        """View the bank transaction history"""
        await self.print_log(ctx, start, num, member.id if member else 0)

    @bank.command(
        name='delete',
        aliases=['remove']
    )
    @is_admin()
    async def bank_delete(self, ctx, transaction_id):
        """Delete a transaction"""
        with self.client.state.get_session() as session:
            session.query(TransactionData).filter_by(_id=transaction_id).delete()
        await ctx.send('Success')

    @bank.command(
        name='pending',
    )
    @is_admin()
    async def bank_pending(self, ctx):
        """View all pending transactions"""
        await self.print_pending(ctx)

    @bank.command(
        name='confirm',
    )
    @is_admin()
    async def bank_confirm_transaction(self, ctx, transaction_id):
        """Confirm a pending transaction"""
        with self.client.state.get_session() as session:
            transaction = session.query(TransactionData).filter_by(_id=transaction_id).one()
            transaction.confirmed = True
        await ctx.send(f'Transaction {transaction_id} confirmed')

    @commands.group(
        name='account',
        aliases=[],
        invoke_without_command=True,
    )
    async def account(self, ctx):
        """View and control your account `+help account`"""
        with self.client.state.get_session() as session:
            # Check if user exists and create entry if it does not
            if session.query(UserData).filter_by(_id=ctx.author.id).count() == 0:
                user = UserData(_id=ctx.author.id, active_char=None)
                session.add(user)
        await self.print_balance(ctx, ctx.author.id)

    @account.command(
        name='add',
    )
    async def account_add(self, ctx, transaction_string=None, *, description=None):
        """Add a transaction to your account `+help account add`

        The transaction_string is a comma separated list of amount and currency pairs.
        example `+bank 2g,5s Pay for last mission`
        example `+bank -2g,-5s Bought food for the kitchen`
        """
        with self.client.state.get_session() as session:
            # Check if user exists and create entry if it does not
            if session.query(UserData).filter_by(_id=ctx.author.id).count() == 0:
                user = UserData(_id=ctx.author.id, active_char=None)
                session.add(user)
            await self.process_transaction(
                ctx, transaction_string, description, ctx.author.id, confirm=False
            )

    @account.command(
        name='history',
        aliases=['log'],
    )
    async def account_history(self, ctx, start=0, num=10):
        """View your account's transaction history"""
        await self.print_log(ctx, start, num, ctx.author.id)

    @account.command(
        name='send',
    )
    async def account_send_money(
        self, ctx, receiver: Member, transaction_string=None, *, description=None
    ):
        """Send Money to another account holder"""
        if '-' in transaction_string:
            await ctx.send('You can only send positive amounts')
            return
        with self.client.state.get_session() as session:
            if session.query(UserData).filter_by(_id=receiver.id).count() == 0:
                await ctx.send('That user does not have an account')
                return
        await self.process_transaction(
            ctx, transaction_string, description, receiver.id, confirm=False, send=True
        )


def setup(client):
    client.add_cog(Bank(client))
