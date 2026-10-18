/**
 * 页面头部组件
 */

import React from 'react';
import { Breadcrumb, Button } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import styles from './PageHeader.module.css';

interface BreadcrumbItem {
  title: string;
  path?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  subTitle?: string;
  breadcrumbs?: BreadcrumbItem[];
  showBack?: boolean;
  extra?: React.ReactNode;
  className?: string;
  onBack?: (() => void) | (() => Promise<void>);
}

const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  subTitle,
  breadcrumbs,
  showBack = false,
  extra,
  className,
  onBack,
}) => {
  const navigate = useNavigate();

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      navigate(-1);
    }
  };
  const displaySubtitle = subtitle || subTitle;

  return (
    <div className={`${styles.pageHeader} ${className || ""}`.trim()}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <Breadcrumb
          className={styles.breadcrumb}
          items={breadcrumbs.map((item) => ({
            title: item.path ? (
              <a onClick={() => navigate(item.path!)}>{item.title}</a>
            ) : (
              item.title
            ),
          }))}
        />
      )}

      <div className={styles.titleRow}>
        <div className={styles.titleSection}>
          {(showBack || !!onBack) && (
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={handleBack}
              className={styles.backButton}
            />
          )}
          <div>
            <h1 className={styles.title}>{title}</h1>
            {displaySubtitle && <p className={styles.subtitle}>{displaySubtitle}</p>}
          </div>
        </div>

        {extra && <div className={styles.extra}>{extra}</div>}
      </div>
    </div>
  );
};

export default PageHeader;
