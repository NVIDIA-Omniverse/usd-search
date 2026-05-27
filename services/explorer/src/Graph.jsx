/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import React from "react";
import {
  Box,
  List,
  ListItem,
  Button,
  Collapse,
  Stack,
  Spinner,
} from "@chakra-ui/react";
import { ChevronRightIcon, ChevronDownIcon } from "@chakra-ui/icons";

function buildTree(data, isInverse) {
  if (!data) {
    return [];
  }
  let { nodes, edges } = data;

  if (!nodes) {
    nodes = [];
  }
  if (!edges) {
    edges = [];
  }

  const nodeMap = {};

  nodes.forEach((node) => {
    nodeMap[node.url] = { ...node, children: [] };
  });

  edges.forEach((edge) => {
    if (!nodeMap[edge.node_1_url]) {
      nodeMap[edge.node_1_url] = { url: edge.node_1_url, children: [] };
    }
    if (!nodeMap[edge.node_2_url]) {
      nodeMap[edge.node_2_url] = { url: edge.node_2_url, children: [] };
    }
  });

  edges.forEach((edge) => {
    let parent, child;
    if (isInverse) {
      parent = nodeMap[edge.node_2_url];
      child = nodeMap[edge.node_1_url];
    } else {
      parent = nodeMap[edge.node_1_url];
      child = nodeMap[edge.node_2_url];
    }
    if (parent && child) {
      parent.children.push(child);
    }
  });

  const childNodeUrls = isInverse
    ? edges.map((edge) => edge.node_1_url)
    : edges.map((edge) => edge.node_2_url);

  const rootNodes = Object.values(nodeMap).filter(
    (node) => !childNodeUrls.includes(node.url),
  );

  // Compute totalChildren for each node
  function computeTotalChildren(node, visited = new Set()) {
    // Safety check: if node has already been visited, return 0 to prevent infinite loop
    if (visited.has(node.url)) {
      console.warn(`Circular reference detected for node: ${node.url}`);
      return 0;
    }
    
    // Add current node to visited set
    visited.add(node.url);
    
    if (!node.children || node.children.length === 0) {
      node.totalChildren = 0;
      return 0;
    } else {
      let total = 0;
      node.children.forEach((child) => {
        total += 1 + computeTotalChildren(child, visited);
      });
      node.totalChildren = total;
      return total;
    }
  }

  rootNodes.forEach((rootNode) => {
    computeTotalChildren(rootNode);
  });

  return rootNodes;
}

const TreeNode = ({ node, expandedNodes, toggleNode }) => {
  const isExpanded = expandedNodes.has(node.url);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <ListItem>
      <Box display="flex" alignItems="center">
        {hasChildren ? (
          <Button
            variant="link"
            onClick={() => toggleNode(node.url)}
            leftIcon={isExpanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
            style={{ userSelect: "text" }}
          >
            {node.url} ({node.totalChildren})
          </Button>
        ) : (
          <Box ml="20px">{node.url}</Box>
        )}
      </Box>
      {hasChildren && (
        <Collapse in={isExpanded} animateOpacity>
          <List pl={4} styleType="none">
            {node.children.map((childNode) => (
              <TreeNode
                key={childNode.url}
                node={childNode}
                expandedNodes={expandedNodes}
                toggleNode={toggleNode}
              />
            ))}
          </List>
        </Collapse>
      )}
    </ListItem>
  );
};

const GraphVisualization = ({ data, isInverse }) => {
  const treeData = React.useMemo(
    () => buildTree(data, isInverse),
    [data, isInverse],
  );
  const [expandedNodes, setExpandedNodes] = React.useState(new Set());

  const allNodeUrls = React.useMemo(() => {
    const urls = new Set();
    function collectUrls(nodes, visited = new Set()) {
      nodes.forEach((node) => {
        // Safety check: if node has already been visited, skip to prevent infinite loop
        if (visited.has(node.url)) {
          console.warn(`Circular reference detected for node: ${node.url}`);
          return;
        }
        
        urls.add(node.url);
        visited.add(node.url);
        
        if (node.children) {
          collectUrls(node.children, visited);
        }
      });
    }
    collectUrls(treeData);
    return urls;
  }, [treeData]);

  const toggleNode = (url) => {
    setExpandedNodes((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(url)) {
        newSet.delete(url);
      } else {
        newSet.add(url);
      }
      return newSet;
    });
  };

  const expandAll = () => {
    setExpandedNodes(new Set(allNodeUrls));
  };

  const collapseAll = () => {
    setExpandedNodes(new Set());
  };

  return (
    <>
      {data && (
        <Box p={4}>
          <Stack direction="row" spacing={4} mb={4}>
            <Button size="sm" onClick={expandAll}>
              Expand All
            </Button>
            <Button size="sm" onClick={collapseAll}>
              Collapse All
            </Button>
          </Stack>
          <List styleType="none">
            {treeData.map((node) => (
              <TreeNode
                key={node.url}
                node={node}
                expandedNodes={expandedNodes}
                toggleNode={toggleNode}
              />
            ))}
          </List>
        </Box>
      )}
      {!data && <Spinner />}
    </>
  );
};

export default GraphVisualization;
