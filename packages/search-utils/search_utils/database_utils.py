# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import re

# standard modules
import sqlite3 as sql
import time
from functools import partial
from typing import List

# local/proprietary modules
from search_utils import log_utils as lu

database_utils_logger = logging.getLogger(__name__)


class AssetDB:
    """Helper class around SQLite API to access, add and/or remove the data from the database.

    Args:
        str db_path: Path to the database file
        list tables: List of tables that need to be created in the database
        list list_keys: List of lists of keys for tables
        list list_key_types: List of lists of key types for the keys of the tables
    """

    def __init__(
        self,
        db_path: str = None,
        tables: list = [],
        list_keys: List[list] = [],
        list_key_types: List[list] = [],
        **kwargs,
    ):
        self.db_path = db_path
        assert self.db_path is not None
        self.tables = tables
        self.list_keys = list_keys
        self.list_key_types = list_key_types
        self.create_tables(self.tables, self.list_keys, self.list_key_types)

    def create_tables(self, tables, list_keys, list_key_types):
        """Connects to the database and create a table based on the list of tables, keys and key_types.

        Args:
            list tables: List of tables that need to be created in the database
            list list_keys: List of lists of keys for tables
            list list_key_types: List of lists of key types for the keys of the tables
        """
        assert len(tables) == len(list_keys) == len(list_key_types)

        # connnects to the table
        conn = sql.connect(self.db_path)
        cursor = conn.cursor()
        # Create table
        try:
            for tbl, keys, key_types in zip(tables, list_keys, list_key_types):
                cmd = "CREATE TABLE IF NOT EXISTS {:}".format(tbl)
                assert len(keys) == len(key_types)
                if len(keys) > 0:
                    cmd += "("
                for key, key_type in zip(keys, key_types):
                    cmd += "{:} {:}, ".format(key, key_type)

                if len(keys) > 0:
                    cmd = cmd[:-2] + ")"
                cursor.execute(cmd)
        except Exception as e:
            database_utils_logger.error("DB table creation failed: " + str(e))

        conn.commit()
        conn.close()

    def insert_row(self, conn, cursor, table_name, new_row, silent=False, replace=False):
        """Insert a row in the database

        Args:
            conn: SQLite database connection
            cursor: SQLite cursor
            str table_name: name of the table where the row need to be added.
            tuple new_row: tuple of elements that will form the row.
            bool silent: If ``False`` the function will print some debuggin info. Default: ``False``.
            bool replace: If ``True`` will replace the row in the database if it already exists. Default: ``False``.
        """
        self.insert_rows(conn, cursor, table_name, [new_row], silent=silent, replace=replace)

    def insert_rows(self, conn, cursor, table_name, new_rows, silent=False, replace=False):
        """Insert a row in the database

        Args:
            conn: SQLite database connection
            cursor: SQLite cursor
            str table_name: name of the table where the row need to be added.
            tuple new_row: tuple of elements that will form the row.
            bool silent: If ``False`` the function will print some debuggin info. Default: ``False``.
            bool replace: If ``True`` will replace the row in the database if it already exists. Default: ``False``.
        """
        assert isinstance(new_rows, list)
        #         assert table_name in self.tables

        if silent:
            add_cmd = "OR IGNORE"
        elif replace:
            add_cmd = "OR REPLACE"
        else:
            add_cmd = ""

        VALUES = ", ".join(["({:})".format(", ".join(["?"] * len(row))) for row in new_rows])
        FIELD_NAMES = ",".join([f["name"] for f in self.get_fields_conn(conn, cursor, table_name)])

        cmd = f"INSERT {add_cmd} INTO {table_name} ({FIELD_NAMES}) VALUES {VALUES}"

        query_content = []
        for r in new_rows:
            query_content += r

        cursor.execute(cmd, query_content)

    def remove_rows(self, conn, cursor, check_id, table_name, id_column):
        """Remove rows from the database.

        Args:
            conn: SQLite database connection
            cursor: SQLite cursor
            check_id: key of the element that needs to be removed
            str table_name: name of the table, where to search for an element
            str id_column: name of the column, where to search for the key
        """
        check_id = f'"{check_id}"'
        # check_id = "'{:}'".format(check_id)
        cursor.execute("DELETE FROM {tn} WHERE {idf}={my_id}".format(tn=table_name, idf=id_column, my_id=check_id))

    def insert(self, table_name: str, new_row, silent: bool = False, replace: bool = False):
        """Wrapper around :func:`insert_row` that opens a connection to the database and passes
        this connection to :func:`insert_row`, which will try to insert an element to the database.

        Args:
            str table_name: name of the table where the row need to be added.
            tuple new_row: tuple of elements that will form the row.
            bool silent: If ``False`` the function will print some debuggin info. Default: ``False``.
            bool replace: If ``True`` will replace the row in the database if it already exists. Default: ``False``.
        """

        # make sure list is passed to insertion command
        if not isinstance(new_row, list):
            new_row = [new_row]

        with SQLContext(sql_db=self) as context:
            try:
                context.insert_rows(table_name, new_row, silent, replace)
            except Exception as e:
                context.conn.rollback()
                database_utils_logger.error(f"Insertion of {new_row[:5]} Failed: {str(e)}")

    def remove(self, check_id, table_name, id_column):
        """Wrapper around :func:`remove_rows` that opens a connection to the database and passes
        this connection to :func:`remove_rows`, which will try to remove an element to the database.

        Args:
            check_id: key of the element that needs to be removed.
            str table_name: name of the table, where to search for an element.
            str id_column: name of the column, where to search for the key.
        """
        with SQLContext(sql_db=self) as context:
            try:
                context.remove_rows(check_id, table_name, id_column)
            except Exception as e:
                context.conn.rollback()
                database_utils_logger.error(f"Removal from the table went wrong: {str(e)}")

    def open_connection(self, multithreaded=False):
        """Opens database connection."""
        conn = sql.connect(self.db_path, check_same_thread=not multithreaded)
        cursor = conn.cursor()
        return conn, cursor

    def close_connection(self, conn):
        """Closes database connection."""
        conn.commit()
        conn.close()

    def drop_table(self, table_name):
        """Removes a table from the database.

        Args:
            str table_name: name of the table that needs to be removed.
        """
        with SQLContext(self) as context:
            try:
                cmd = f"DROP TABLE {table_name}"
                context.cursor.execute(cmd)
            except Exception as e:
                context.conn.rollback()
                database_utils_logger.error(f"Table drop Failed: {str(e)}")

    def get_row(self, check_id, table_name, id_column, column="*", single: bool = True):
        """Returns the list of entries from the database that match the provided key.

        Args:
            check_id: key of the element.
            str table_name: name of the table, where to search for an element.
            str id_column: name of the column, where to search for the key.
        """
        with SQLContext(self) as sc:
            id_exists = sc.get_row_conn(check_id, table_name, id_column, column=column, single=single)

        return id_exists

    def get_row_conn(self, conn, cursor, check_id, table_name, id_column, column="*", single=True):
        """Returns the list of entries from the database that match the provided key. This function is triggered by :py:mod:`AssetDB.get_row`."""
        check_id = check_id.replace("'", "''")
        check_id = f"'{check_id}'"
        id_exists = None

        try:
            cursor.execute(f"SELECT {column} FROM {table_name} WHERE {id_column}={check_id}")
            if single:
                id_exists = cursor.fetchone()
            else:
                id_exists = cursor.fetchall()
        except Exception as e:
            database_utils_logger.exception(f"Table check went wrong: {str(e)}")
        return id_exists

    def check_if_exists(self, check_id, table_name, id_column):
        """Returns ``True`` if an element exists in the table. Check :func:`get_row` for the list of arguments."""
        id_exists = self.get_row(check_id, table_name, id_column)
        return id_exists is not None

    def describe_db(self, output=None, tablesToIgnore: list = [], slim_info: bool = False, **kwargs):
        """Print the statistics of the Database to the stdout or the provided file location.

        Args:
            output: If ``None`` - will print to stdout, if ``str`` - returns the description as a string. Default: ``None``.
            list tablesToIgnore: list of tables that need to be ignored in the output. Default: ``[]``.
            bool slim_info: if ``True`` prints a shorter version of the description. Default: ``False``.
        """

        buf = ""
        totalTables = 0
        totalRows = 0

        if not slim_info:
            totalColumns = 0
            totalCells = 0

        with SQLContext(self) as sc:
            try:
                if slim_info:
                    buf += "\nTableName\tRows\n"
                    buf += "{:}\n".format("-" * 20)
                else:
                    buf += "\nTableName\tColumns\tRows\tCells\n"
                    buf += "{:}\n".format("-" * 40)

                # Get List of Tables:
                tableListQuery = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY Name"
                sc.cursor.execute(tableListQuery)
                tables = map(lambda t: t[0], sc.cursor.fetchall())

                for table in tables:
                    if table in tablesToIgnore:
                        continue

                    rowsQuery = f"SELECT Count() FROM {table}"
                    sc.cursor.execute(rowsQuery)
                    numberOfRows = sc.cursor.fetchone()[0]

                    if not slim_info:
                        columnsQuery = f"PRAGMA table_info({table})"
                        sc.cursor.execute(columnsQuery)
                        numberOfColumns = len(sc.cursor.fetchall())

                        numberOfCells = numberOfColumns * numberOfRows

                    if slim_info:
                        buf += "%s\t\t%d\n" % (table, numberOfRows)
                    else:
                        buf += "%s\t\t%d\t%d\t%d\n" % (
                            table,
                            numberOfColumns,
                            numberOfRows,
                            numberOfCells,
                        )

                    totalTables += 1
                    totalRows += numberOfRows
                    if not slim_info:
                        totalColumns += numberOfColumns
                        totalCells += numberOfCells

                if not slim_info:
                    buf += (
                        "{:}\n".format("-" * 40)
                        + f"Total Number of Columns:\t{totalColumns:d}\n"
                        + f"Total Number of Rows:\t\t{totalRows:d}\n"
                        + f"Total Number of Cells:\t\t{totalCells:d}\n"
                        + "{:}\n".format("-" * 40)
                    )
            except Exception as e:
                database_utils_logger.error("DB description failed: " + str(e))

        if output is None:
            database_utils_logger.info(buf)
            return
        elif output == "str":
            return buf

    def get_all(self, table_name, col_name="*", **kwargs):
        """Return all the entries in the table.

        Args:
            str table_name: name of the table.
        """
        with SQLContext(self) as sc:
            id_exists = sc.get_all_conn(table_name, col_name, **kwargs)

        return id_exists

    def count_all(self, table_name):
        """Return all the entries in the table.

        Args:
            str table_name: name of the table.
        """
        with SQLContext(self) as sc:
            id_exists = sc.get_all_conn(table_name, "COUNT()")

        return id_exists

    def get_all_conn(
        self,
        conn,
        cursor,
        table_name,
        col_name="*",
        filter_field: str = None,
        filter_by: str = None,
        nocase: bool = True,
        limit: int = None,
    ):
        """Return all the entries in the table.

        Args:
            str table_name: name of the table.
        """
        id_exists = []

        conditions = []
        # filtering
        if filter_field is not None:
            conditions.append(f"{filter_field} LIKE '{filter_by}' {'COLLATE NOCASE' if nocase else ''}")

        if len(conditions) > 0:
            cond = "WHERE " + " AND ".join(conditions)
        else:
            cond = ""

        if limit is not None:
            limit = f"LIMIT {limit}"
        else:
            limit = ""

        try:
            cursor.execute(f"SELECT {col_name} FROM {table_name} {cond} {limit}")
            id_exists = cursor.fetchall()

            if isinstance(id_exists, tuple):
                id_exists = [id_exists]
        except Exception as e:
            database_utils_logger.error(f"Listing of the DB at path: '{self.db_path}' failed: {str(e)}")

        return id_exists

    def list_all(self, table_name):
        """Print all entries in the table. Check :func:`get_all` for argument description."""
        id_exists = self.get_all(table_name)
        for el in id_exists:
            row = (el[0], el[-1])
            database_utils_logger.info(f"{row}")

    def find_element(self, find_id, table, column, **kwargs):
        """Check :py:func:`find_element_conn` for details."""
        with SQLContext(self) as sc:
            res = self.find_element_conn(sc.conn, sc.cursor, find_id, table, column, **kwargs)
        return res

    def find_element_conn(
        self,
        conn,
        cursor,
        find_id: str,
        table: str,
        column: str,
        sort_by: str = None,
        thresh_field: str = None,
        thresh_val: float = 0.1,
        top_n: int = -1,
        filter_field: str = None,
        filter_by: str = None,
        nocase: bool = True,
        **kwargs,
    ) -> list:
        """Returns a set of elements from the database that correspond to the search criteria.

        Args:
            conn: Sqlite database connection
            cursor: Sqlite database cursor
            find_id (str): string or a list of keys which needs to be found in the table.
            table (str): name of the table that needs to be searched.
            column (str): name of the column that should contain a requested key.
            sort_by (str, optional): if not ``None`` the output will be sorted by this column name. Defaults to None.
            thresh_field (str, optional): if not ``None`` the output rows with the ``thresh_field`` value lower than ``thresh_val`` will be removed from the search. Defaults to None.
            thresh_val (float, optional): value of the threshold that is used by the previous parameter. Defaults to ``0.1``.
            top_n (int, optional): number of elements that need to be returned, if available. If negative - returns all the elements from DB. Defaults to -1.
            filter_field (str, optional): field where filtering should be applied. Defaults to ``None``.
            filter_by (str, optional): filtering pattern which is applied to the data. Defaults to ``None``.
            nocase (bool, optional): if ``True`` will do case insensitive search. Defaults to ``True``.

        Returns:
            list: list fo items from the database
        """
        # check that the imports are properly set
        if filter_field is not None:
            assert filter_by is not None, "filtering value is not provided"

        if not isinstance(find_id, list):
            find_id = [find_id]

        def wrapper(input, cond):
            """Small wrapper that checks condition and returns input if True and '' otherwise."""
            return input if cond else ""

        # get additional sql flags
        sql_flags = [
            wrapper(f"AND {filter_field} LIKE '{filter_by}'", filter_field is not None),
            wrapper(f"AND {thresh_field} > {thresh_val}", thresh_field is not None),
            wrapper(f"ORDER BY {sort_by} DESC", sort_by is not None),
            wrapper(f"LIMIT {top_n}", top_n > 0),
        ]

        # clean the flags string
        add_flag = " ".join(sql_flags).strip(" ")
        add_flag = re.sub(" +", " ", add_flag)

        # Connecting to the database file

        try:
            results = []
            for id in find_id:
                cursor.execute(
                    f"SELECT * FROM {table} WHERE {column} = '{id}' {wrapper('COLLATE NOCASE', nocase)} {add_flag}"
                )
                id_exists = cursor.fetchall()
                if isinstance(id_exists, tuple):
                    id_exists = [id_exists]

                results.extend(id_exists)

        except Exception as e:
            database_utils_logger.error("Searching in the DB failed: " + str(e))

        return results

    def create_index(self, table, column):
        """Create and index for a table.

        Args:
            str table: name of the table for which the index will be created.
            str column: name of the column that is used for index creation.
        """
        with SQLContext(self) as sc:
            index_created = False
            while not index_created:
                try:
                    sql_cmd = "CREATE INDEX index_{:}_{:} ON {:} ({:})".format(table, column, table, column)
                    sc.cursor.execute(sql_cmd)
                    index_created = True
                except Exception as e:
                    database_utils_logger.error(f"Index was not created: {str(e)}")
                    sc.cursor.execute(f"DROP INDEX index_{table}_{column}")
                    time.sleep(0.1)

    def get_batch(self, table, column, last, n_elements=100, **kwargs):
        """Returns a set of elements of the fixed size from the database that corresponds to a search criteria and starts from the provided elemnt ID.

        Args:
            str table: name of the table that needs to be searched.
            str column: name of the column that should contain a requested key.
            last: element that was retrieved last.
            int n_elements: number of elements that need to be retrieved from the database.
            str,None sort_by: if not ``None`` the output will be sorted by this column name. Default: ``None``.
        """

        sort_by = kwargs.get("sort_by", None)
        with SQLContext(self) as sc:
            add_flag = "ORDER BY {ord} DESC".format(ord=sort_by) if sort_by is not None else ""
            # get table ID
            table_id = self.get_column_id(table, column)

            try:
                sc.cursor.execute(
                    "SELECT * FROM {tn} WHERE {idf}<{last} {add_flag} LIMIT {n_elements}".format(
                        tn=table,
                        idf=column,
                        last=last,
                        add_flag=add_flag,
                        n_elements=n_elements,
                    )
                )
                id_exists = sc.cursor.fetchall()

                if isinstance(id_exists, tuple):
                    id_exists = [id_exists]

                last_element = id_exists[-1][table_id]

            except Exception as e:
                id_exists = []
                last_element = None
                database_utils_logger.error("Searching in the DB failed: " + str(e))

        return id_exists, last_element

    def get_column_id(self, table_name, column_name, **kwargs):
        """Return ID of the colum based on its name.

        Args:
            str table_name: name of the table, where to search for the column.
            str column_name: name of the column that needs to be found.
            cursor: if ``None`` opens the connection with :func:`open_connection`, otherwise use the provided cursor for the connection.
        """
        cursor = kwargs.get("cursor", None)

        if cursor is None:
            connection, cursor = self.open_connection()
            close_cursor = True

        columnsQuery = "PRAGMA table_info({:})".format(table_name)
        cursor.execute(columnsQuery)
        for it, el in enumerate(list(cursor.fetchall())):
            if el[1] == column_name:
                break

        if close_cursor:
            cursor.close()
            connection.close()
        return it

    def get_tables(self) -> list:
        """Get a list of tables from the database."""
        conn, cursor = self.open_connection()
        tableListQuery = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY Name"
        cursor.execute(tableListQuery)
        tables = map(lambda t: t[0], cursor.fetchall())
        self.close_connection(conn)
        return list(tables)

    def get_fields(self, table):
        """Get a dictionary with the table columns and all the information about them."""
        with SQLContext(self) as c:
            result = self.get_fields_conn(c.conn, c.cursor, table)
        return result

    @staticmethod
    def get_fields_conn(conn, cursor, table):
        """Get a dictionary with the table columns and all the information about them."""
        columnsQuery = "PRAGMA table_info(%s)" % table
        cursor.execute(columnsQuery)
        rows = cursor.fetchall()
        return [{"name": row[1], "type": row[2], "primary": row[5]} for row in rows]

    def get_kwargs(self) -> dict:
        """Get a dictionary that outputs the list of tables, table keys and table key types for the database."""
        tables = self.get_tables()
        return {
            "tables": self.get_tables(),
            "list_keys": [[f["name"] for f in self.get_fields(t)] for t in tables],
            "list_key_types": [
                [f["type"] + (" PRIMARY KEY" if f["primary"] == 1 else "") for f in self.get_fields(t)] for t in tables
            ],
        }

    @staticmethod
    def merge_databases(db1_path, db2_path, out_path, merge_by="path"):
        """Note: Assumes that the databases are of completely same structure."""
        # connect to the databases
        db1 = AssetDB(db_path=db1_path)
        db2 = AssetDB(db_path=db2_path)

        # create a directory for the output
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        # read the database set up
        kwargs = db1.get_kwargs()
        # create the database for merging the tables
        merge_db = AssetDB(db_path=out_path, **kwargs)

        # per table copy from db1
        for it, db in enumerate([db1, db2]):
            tables = db.get_tables()
            for t in tables:
                cols = [f["name"] for f in db.get_fields("data")]
                if merge_by in cols:
                    data = db.get_all(t, merge_by)
                    with lu.print_wrapper(
                        f"[Database {it+1}, '{t}', read by '{merge_by}']",
                        print_after=False,
                        logger=database_utils_logger.info,
                    ):
                        for key in data:
                            row = db.get_row(key[0], t, merge_by)
                            merge_db.insert(t, row, silent=True)
                else:
                    data = db.get_all(t)
                    with lu.print_wrapper(
                        f"[Database {it+1}, '{t}']",
                        print_after=False,
                        logger=database_utils_logger.info,
                    ):
                        for row in data:
                            merge_db.insert(t, row, silent=True)

    @staticmethod
    def copy_table(input_db, output_db, table_name: str, index_name: str, overwite=False):
        """Copy the table from one DB to another one. Note: the code does everything in one transaction."""
        list_indexes = input_db.get_all(table_name, index_name)

        with SQLContext(output_db) as context:
            with lu.print_wrapper(
                f"copying table '{table_name}'",
                print_after=False,
                logger=database_utils_logger.info,
            ):
                for ind in list_indexes:
                    row = input_db.get_row(ind[0], table_name, index_name)
                    if overwite or not output_db.check_if_exists(ind[0], table_name, index_name):
                        output_db.insert_row(context.conn, context.cursor, table_name, row, replace=True)


class SQLContext:
    """SQL Context that can be used in ``with`` statement.
    It creates connection to an SQL database on ``__enter__`` and does commit and close connection on ``__exit__``.

    Args:
        AssetDB sql_db: SQLite database
        bool enabled: if ``False`` will skip database connection (can be used for debugging)
        bool multithreaded: if ``True`` allows for multi-threaded SQLite connections (``Note``: experimental feature)
        logger: logging function
    """

    def __init__(
        self,
        sql_db: AssetDB = None,
        enabled: bool = True,
        multithreaded: bool = False,
        logger=database_utils_logger.debug,
    ):
        self.enabled = enabled
        self.logger = logger
        if self.enabled:
            self.sql_db = sql_db
            self.multithreaded = multithreaded

        # register some functions
        self.register_funcs = [
            "insert_row",
            "insert_rows",
            "get_row_conn",
            "remove_rows",
            "find_element_conn",
            "get_fields_conn",
            "get_all_conn",
        ]

    def commit(self):
        """Commit changes to the database if the context is enabled."""
        if self.enabled:
            self.conn.commit()

    def __enter__(self):
        if self.enabled:
            self.conn, self.cursor = self.sql_db.open_connection(multithreaded=self.multithreaded)
            self.logger("transaction started")

            for f in self.register_funcs:
                self.register_func(f)

        return self

    def __exit__(self, *args, **kwargs):
        if self.enabled:
            # commit transaction
            self.commit()
            self.logger("transaction finished")
            # close connection
            self.sql_db.close_connection(self.conn)

    def register_func(self, fname: str):
        """Register function as class method with pre-set client parameter.

        Args:
            str fname: name of the function that need to be registered
        """
        setattr(self, fname, partial(getattr(self.sql_db, fname), self.conn, self.cursor))
