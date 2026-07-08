START TRANSACTION;

CREATE TABLE IF NOT EXISTS `document_task_batches` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '批次ID',
  `space_id` BIGINT NOT NULL COMMENT '空间ID',
  `kb_id` BIGINT NOT NULL COMMENT '知识库ID',
  `creator_id` BIGINT NOT NULL COMMENT '触发人ID',
  `action` SMALLINT NOT NULL DEFAULT 0 COMMENT '批次动作: 0=process,1=reprocess,2=retry',
  `status` SMALLINT NOT NULL DEFAULT 0 COMMENT '批次状态: 0=pending,1=processing,2=completed,3=failed,4=partial_failed,5=cancelled',
  `total_count` SMALLINT NOT NULL DEFAULT 0 COMMENT '批次文档总数',
  `task_summary` JSON NULL COMMENT '任务聚合摘要',
  `note` VARCHAR(255) NULL COMMENT '批次说明',
  `error_message` TEXT NULL COMMENT '批次级错误信息',
  `started_at` DATETIME NULL COMMENT '开始时间',
  `completed_at` DATETIME NULL COMMENT '完成时间',
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_document_task_batch_kb_status` (`kb_id`, `status`),
  KEY `ix_document_task_batches_space_id` (`space_id`),
  KEY `ix_document_task_batches_kb_id` (`kb_id`),
  KEY `ix_document_task_batches_creator_id` (`creator_id`),
  CONSTRAINT `fk_document_task_batches_space_id`
    FOREIGN KEY (`space_id`) REFERENCES `knowledge_spaces` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_document_task_batches_kb_id`
    FOREIGN KEY (`kb_id`) REFERENCES `knowledge_bases` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_document_task_batches_creator_id`
    FOREIGN KEY (`creator_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档处理批次表';

ALTER TABLE `document_tasks`
  ADD COLUMN `batch_id` BIGINT NULL COMMENT '所属批次ID' AFTER `id`;

ALTER TABLE `document_tasks`
  ADD INDEX `ix_document_tasks_batch_id` (`batch_id`);

ALTER TABLE `document_tasks`
  ADD CONSTRAINT `fk_document_tasks_batch_id`
    FOREIGN KEY (`batch_id`) REFERENCES `document_task_batches` (`id`) ON DELETE SET NULL;

COMMIT;
